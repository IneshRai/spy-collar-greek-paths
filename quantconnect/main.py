# region imports
from AlgorithmImports import *
# endregion


class CollarGreekPathCollector(QCAlgorithm):
    """
    Collects aggregate Greek paths for a large sample of SPY bear put-spread collars.

    Each collar is a 3-leg structure opened on a fixed cadence:
        + 1 long  put   (the floor)
        - 1 short put   (sits below the floor, defines the put-spread / buffer width)
        - 1 short call  (the cap that finances the structure)

    We hold each collar to expiration and, once per trading day, read the per-share
    Greeks of every leg from the option chain, scale by signed quantity * 100, and log
    the aggregate position Greeks together with the held-day index.

    IMPORTANT: this is a MEASUREMENT-ONLY algorithm. It places no trades. We track
    "virtual" collars so each Greek path is clean and free of fill/assignment noise.
    Output is one row per collar per trading day -> the input to the local analysis.

    What we log per row (see HEADER below):
        collar_id, entry_date, date, held_days (trading days since entry, 0 at entry),
        held_days_cal (calendar days), dte (calendar days to expiry), underlying spot,
        aggregate delta/gamma/theta/vega (per 1 collar, 100x multiplier baked in),
        and the three strikes.
    """

    def Initialize(self):
        # ---- backtest window (extend for a bigger sample; longer = slower) ----
        self.SetStartDate(2020, 1, 1)
        self.SetEndDate(2024, 12, 31)
        self.SetCash(1_000_000)          # unused (no trades) but required by the engine

        # ---- strategy parameters (tune here) -------------------------------------
        self.TARGET_DTE         = 35     # aim for the expiry closest to this many calendar days
        self.MIN_DTE            = 21     # never pick an expiry closer than this
        self.MAX_DTE            = 60     # never pick an expiry further than this
        self.ENTRY_CADENCE      = 5      # open a new collar every N trading days (5 ~= weekly)
        self.LONG_PUT_OFFSET    = 0.00   # long  put strike vs spot (0% = ATM floor)
        self.SHORT_PUT_OFFSET   = -0.07  # short put strike vs spot (-7% => ~7% buffer width)
        self.SHORT_CALL_OFFSET  = 0.04   # short call strike vs spot (+4% cap)
        self.INCLUDE_UNDERLYING = False  # if True, add +100 delta/collar for a long-SPY overlay

        # ---- option-chain subscription (widen if collars drop out on big moves) ---
        self.OPTION_RESOLUTION  = Resolution.Daily   # switch to Resolution.Minute if your
                                                     # data subscription has no daily options
        self.STRIKE_RANGE       = 45     # +/- strikes around ATM to subscribe
        self.EXPIRY_MIN         = 0
        self.EXPIRY_MAX         = 65

        # ---- securities ----------------------------------------------------------
        equity = self.AddEquity("SPY", self.OPTION_RESOLUTION)
        self.spy = equity.Symbol

        option = self.AddOption("SPY", self.OPTION_RESOLUTION)
        option.SetFilter(lambda u: u.Strikes(-self.STRIKE_RANGE, self.STRIKE_RANGE)
                                    .Expiration(self.EXPIRY_MIN, self.EXPIRY_MAX))
        # Greeks are only populated when a price model is set on the option security.
        option.PriceModel = OptionPriceModels.BlackScholes()
        self.option_symbol = option.Symbol

        # ---- state ---------------------------------------------------------------
        self.active_collars   = []          # list of open virtual-collar dicts
        self.collar_seq       = 0           # running id
        self.days_since_entry = 10 ** 9     # large -> eligible to open on first chance
        self.last_scan_date   = None        # so we process at most once per calendar day

        # ---- funnel counters (diagnostics) ---------------------------------------
        self.n_entry_attempts      = 0
        self.n_entry_success       = 0
        self.n_entry_skipped_chain = 0
        self.n_entry_skipped_legs  = 0
        self.n_obs_logged          = 0
        self.n_obs_skipped_greeks  = 0
        self.n_obs_skipped_missing = 0

        # ---- output --------------------------------------------------------------
        self.HEADER = ("collar_id,entry_date,date,held_days,held_days_cal,dte,"
                       "underlying,agg_delta,agg_gamma,agg_theta,agg_vega,"
                       "k_long_put,k_short_put,k_short_call")
        self.rows = []
        self.Log("HEADER," + self.HEADER)   # makes the header recoverable straight from the log

        # heartbeat (monthly): proves the algo is alive and shows running totals
        self.Schedule.On(self.DateRules.MonthStart(self.spy),
                         self.TimeRules.AfterMarketOpen(self.spy, 1),
                         self.Heartbeat)

    # =============================================================================
    def OnData(self, data):
        if self.option_symbol not in data.OptionChains:
            return
        chain = data.OptionChains[self.option_symbol]
        if chain is None or len(list(chain)) == 0:
            return

        # process at most once per calendar day (also makes Minute resolution cheap)
        today = self.Time.date()
        if today == self.last_scan_date:
            return
        self.last_scan_date = today

        spot = self.Securities[self.spy].Price
        if spot == 0:
            return

        by_symbol = {c.Symbol: c for c in chain}

        # ---- 1) update every open collar with today's Greeks --------------------
        still_open = []
        for collar in self.active_collars:
            if today > collar["expiry"]:
                continue                       # expired -> drop it
            collar["held_days"] += 1           # count every trading day held
            agg = self._aggregate_greeks(collar, by_symbol)
            if agg is not None:
                self._record(collar, spot, agg)
            still_open.append(collar)          # keep even if today's read failed
        self.active_collars = still_open

        # ---- 2) maybe open a new collar -----------------------------------------
        self.days_since_entry += 1
        if self.days_since_entry >= self.ENTRY_CADENCE:
            self._try_open_collar(chain, by_symbol, spot)
            self.days_since_entry = 0

    # =============================================================================
    def _try_open_collar(self, chain, by_symbol, spot):
        self.n_entry_attempts += 1
        today = self.Time.date()

        # candidate expiries inside the DTE band
        expiries = sorted({c.Expiry.date() for c in chain})
        valid = [e for e in expiries
                 if self.MIN_DTE <= (e - today).days <= self.MAX_DTE]
        if not valid:
            self.n_entry_skipped_chain += 1
            return
        expiry = min(valid, key=lambda e: abs((e - today).days - self.TARGET_DTE))

        puts = sorted([c for c in chain
                       if c.Expiry.date() == expiry and c.Right == OptionRight.Put],
                      key=lambda c: c.Strike)
        calls = sorted([c for c in chain
                        if c.Expiry.date() == expiry and c.Right == OptionRight.Call],
                       key=lambda c: c.Strike)
        if not puts or not calls:
            self.n_entry_skipped_chain += 1
            return

        k_lp = spot * (1 + self.LONG_PUT_OFFSET)
        k_sp = spot * (1 + self.SHORT_PUT_OFFSET)
        k_sc = spot * (1 + self.SHORT_CALL_OFFSET)

        long_put   = min(puts,  key=lambda c: abs(c.Strike - k_lp))
        short_put  = min(puts,  key=lambda c: abs(c.Strike - k_sp))
        short_call = min(calls, key=lambda c: abs(c.Strike - k_sc))

        # the long put must sit ABOVE the short put (protection band below the floor)
        if short_put.Strike >= long_put.Strike:
            self.n_entry_skipped_legs += 1
            return

        self.collar_seq += 1
        collar = {
            "id":           self.collar_seq,
            "entry_date":   today,
            "expiry":       expiry,
            "held_days":    0,
            "legs":         [(long_put.Symbol,   +1.0),
                             (short_put.Symbol,  -1.0),
                             (short_call.Symbol, -1.0)],
            "k_long_put":   long_put.Strike,
            "k_short_put":  short_put.Strike,
            "k_short_call": short_call.Strike,
        }

        # record the t=0 observation right away
        agg = self._aggregate_greeks(collar, by_symbol)
        if agg is None:
            self.collar_seq -= 1
            self.n_entry_skipped_legs += 1
            return
        self._record(collar, spot, agg)
        self.active_collars.append(collar)
        self.n_entry_success += 1

    # =============================================================================
    def _aggregate_greeks(self, collar, by_symbol):
        """Sum signed_qty * 100 * per-share Greek across the three legs. None if any
        leg is missing from the chain or carries unpriced (all-zero) Greeks."""
        d = g = t = v = 0.0
        mult = 100.0
        for sym, qty in collar["legs"]:
            c = by_symbol.get(sym, None)
            if c is None:
                self.n_obs_skipped_missing += 1
                return None
            gr = c.Greeks
            if gr is None or (gr.Delta == 0 and gr.Gamma == 0
                              and gr.Theta == 0 and gr.Vega == 0):
                self.n_obs_skipped_greeks += 1
                return None
            d += qty * mult * gr.Delta
            g += qty * mult * gr.Gamma
            t += qty * mult * gr.Theta
            v += qty * mult * gr.Vega
        if self.INCLUDE_UNDERLYING:
            d += 100.0   # one long 100-share lot hedged by the collar
        return (d, g, t, v)

    # =============================================================================
    def _record(self, collar, spot, agg):
        d, g, t, v = agg
        today = self.Time.date()
        dte = (collar["expiry"] - today).days
        held_cal = (today - collar["entry_date"]).days
        row = (f'{collar["id"]},{collar["entry_date"]},{today},'
               f'{collar["held_days"]},{held_cal},{dte},'
               f'{spot:.4f},{d:.4f},{g:.6f},{t:.4f},{v:.4f},'
               f'{collar["k_long_put"]:.2f},{collar["k_short_put"]:.2f},'
               f'{collar["k_short_call"]:.2f}')
        self.rows.append(row)
        self.Log("DATA," + row)
        self.n_obs_logged += 1

    # =============================================================================
    def Heartbeat(self):
        self.Log(f"HEARTBEAT {self.Time.date()} | active={len(self.active_collars)} "
                 f"| opened={self.n_entry_success} | obs={self.n_obs_logged}")

    def OnEndOfAlgorithm(self):
        self.Log("==== FUNNEL ====")
        self.Log(f"entry_attempts       = {self.n_entry_attempts}")
        self.Log(f"entry_success        = {self.n_entry_success}")
        self.Log(f"entry_skipped_chain  = {self.n_entry_skipped_chain}")
        self.Log(f"entry_skipped_legs   = {self.n_entry_skipped_legs}")
        self.Log(f"obs_logged           = {self.n_obs_logged}")
        self.Log(f"obs_skipped_greeks   = {self.n_obs_skipped_greeks}")
        self.Log(f"obs_skipped_missing  = {self.n_obs_skipped_missing}")
        # backup export: full CSV to the ObjectStore (download from the Object Store tab)
        csv = self.HEADER + "\n" + "\n".join(self.rows)
        key = "collar_greek_paths.csv"
        self.ObjectStore.Save(key, csv)
        self.Log(f"Saved {len(self.rows)} rows to ObjectStore key '{key}'")
