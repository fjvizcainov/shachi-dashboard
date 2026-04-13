"""
Macro Regime Filter — Phase 2

Classifies the current market environment into one of five regimes:
  BULL      — SPY above SMA200, VIX < 20
  NEUTRAL   — SPY near SMA200 or VIX 20-25
  BEAR      — SPY below SMA200 or VIX > 25
  HIGH_VOL  — VIX > 30
  CRISIS    — VIX > 40 or intraday SPY gap > 3%

Each regime adjusts:
  - max_position_pct (sizing)
  - max_positions (concentration)
  - allowed_sides (LONG only in BEAR/CRISIS)
  - signal_threshold (screener gate)
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional, Dict
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import config

logger = logging.getLogger(__name__)


@dataclass
class RegimeParams:
    """Risk parameters for a market regime."""
    name:               str
    max_position_pct:   float   # Max % of equity per position
    max_positions:      int     # Max concurrent positions
    allowed_sides:      tuple   # ("long",) or ("long", "short")
    signal_threshold:   float   # Min screener score to trigger Claude
    kelly_fraction:     float   # Multiplier on raw Kelly size
    description:        str


REGIME_TABLE: Dict[str, RegimeParams] = {
    "BULL": RegimeParams(
        name="BULL",
        max_position_pct=0.22,
        max_positions=6,
        allowed_sides=("long", "short"),
        signal_threshold=7.0,
        kelly_fraction=0.50,  # Half-Kelly
        description="SPY > SMA200, VIX < 20 — full risk on",
    ),
    "NEUTRAL": RegimeParams(
        name="NEUTRAL",
        max_position_pct=0.18,
        max_positions=5,
        allowed_sides=("long", "short"),
        signal_threshold=7.5,
        kelly_fraction=0.40,
        description="Mixed signals — moderate sizing",
    ),
    "BEAR": RegimeParams(
        name="BEAR",
        max_position_pct=0.12,
        max_positions=4,
        allowed_sides=("long", "short"),  # Shorts are primary opportunity in downtrend
        signal_threshold=7.5,
        kelly_fraction=0.25,
        description="SPY < SMA200 or VIX > 25 — reduce longs, prefer shorts",
    ),
    "HIGH_VOL": RegimeParams(
        name="HIGH_VOL",
        max_position_pct=0.12,
        max_positions=4,
        allowed_sides=("long", "short"),  # Shorts thrive in high-vol selloffs
        signal_threshold=7.0,
        kelly_fraction=0.30,
        description="VIX > 30 — wide ATR, reduce sizing, shorts preferred",
    ),
    "CRISIS": RegimeParams(
        name="CRISIS",
        max_position_pct=0.08,
        max_positions=3,
        allowed_sides=("long", "short"),  # Shorts are the primary edge in crashes
        signal_threshold=6.5,
        kelly_fraction=0.15,
        description="VIX > 40 — crash mode, small size, shorts only on confirmed breakdowns",
    ),
}


class RegimeFilter:
    """
    Determines the current macro regime and returns the corresponding
    risk parameters. Cached for 5 minutes.
    """

    def __init__(self):
        self._cache_regime: Optional[str] = None
        self._cache_ts: float = 0
        self._cache_ttl: int  = 300  # 5 minutes

        self._alpaca_key    = config.alpaca.api_key
        self._alpaca_secret = config.alpaca.secret_key
        self._polygon_key   = config.polygon.api_key

        # FIX: persist last known VIX so data gaps don't silently default to 20
        self._last_vix: Optional[float] = None

    # ─── Data helpers ─────────────────────────────────────────────────────────

    def _get_spy_data(self) -> Optional[Dict]:
        """Fetch SPY daily bars (60 days) from Alpaca."""
        try:
            url = "https://data.alpaca.markets/v2/stocks/SPY/bars"
            params = {"timeframe": "1Day", "limit": 220, "sort": "asc"}
            resp = requests.get(
                url,
                headers={
                    "APCA-API-KEY-ID": self._alpaca_key,
                    "APCA-API-SECRET-KEY": self._alpaca_secret,
                },
                params=params,
                timeout=8,
            )
            if resp.status_code != 200:
                return None

            bars = resp.json().get("bars", [])
            if len(bars) < 50:
                return None

            closes = [float(b["c"]) for b in bars]
            latest = closes[-1]
            sma200 = sum(closes[-200:]) / min(200, len(closes))
            sma50  = sum(closes[-50:]) / 50
            open_today = float(bars[-1]["o"])
            prev_close = closes[-2] if len(closes) >= 2 else closes[-1]
            gap_pct    = (open_today / prev_close - 1) * 100

            return {
                "price":   latest,
                "sma200":  sma200,
                "sma50":   sma50,
                "gap_pct": gap_pct,
                "above_sma200": latest > sma200,
                "above_sma50":  latest > sma50,
            }
        except Exception as e:
            logger.warning(f"SPY data fetch failed: {e}")
            return None

    def _get_vix(self) -> Optional[float]:
        """Fetch latest VIX from Polygon."""
        try:
            url = f"https://api.polygon.io/v2/aggs/ticker/I:VIX/range/1/day/2020-01-01/9999-12-31"
            resp = requests.get(
                url,
                params={"apiKey": self._polygon_key, "limit": 5, "sort": "desc"},
                timeout=8,
            )
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                if results:
                    vix = float(results[0]["c"])
                    self._last_vix = vix
                    return vix
        except Exception:
            pass

        # Fallback: try Alpaca VIXY as a proxy
        try:
            url = "https://data.alpaca.markets/v2/stocks/VIXY/bars"
            resp = requests.get(
                url,
                headers={
                    "APCA-API-KEY-ID": self._alpaca_key,
                    "APCA-API-SECRET-KEY": self._alpaca_secret,
                },
                params={"timeframe": "1Day", "limit": 3, "sort": "desc"},
                timeout=5,
            )
            if resp.status_code == 200:
                bars = resp.json().get("bars", [])
                if bars:
                    vix = float(bars[0]["c"]) * 1.4  # rough VIX proxy from VIXY
                    self._last_vix = vix
                    return vix
        except Exception:
            pass

        # FIX: use last known VIX instead of blindly defaulting to 20 (too optimistic)
        if self._last_vix is not None:
            logger.warning(
                f"Could not fetch VIX — using last known value {self._last_vix:.1f}"
            )
            return self._last_vix

        logger.warning("Could not fetch VIX — no prior value, defaulting to 25 (conservative)")
        return 25.0

    # ─── Regime detection ─────────────────────────────────────────────────────

    def _classify(self, spy: Dict, vix: float) -> str:
        """Apply regime rules and return regime name."""
        if vix >= 40 or abs(spy.get("gap_pct", 0)) > 3.0:
            return "CRISIS"

        if vix >= 30:
            return "HIGH_VOL"

        if not spy.get("above_sma200") or vix >= 25:
            return "BEAR"

        if spy.get("above_sma200") and spy.get("above_sma50") and vix < 20:
            return "BULL"

        return "NEUTRAL"

    def get_regime(self, force_refresh: bool = False) -> RegimeParams:
        """
        Return the current regime parameters (cached 5 min).
        On data failure returns NEUTRAL (safe default).
        """
        now = time.time()
        if not force_refresh and self._cache_regime and (now - self._cache_ts < self._cache_ttl):
            return REGIME_TABLE[self._cache_regime]

        spy = self._get_spy_data()
        vix = self._get_vix()

        if spy is None:
            logger.warning("Regime filter: SPY data unavailable, defaulting to NEUTRAL")
            regime_name = "NEUTRAL"
        else:
            regime_name = self._classify(spy, vix)  # _get_vix() guaranteed non-None (falls back to _last_vix or 25.0)

        self._cache_regime = regime_name
        self._cache_ts     = now

        params = REGIME_TABLE[regime_name]
        logger.info(
            f"Regime: {regime_name} "
            f"(SPY={'%.2f' % spy['price'] if spy else 'N/A'} "
            f"SMA200={'%.2f' % spy['sma200'] if spy else 'N/A'} "
            f"VIX={vix:.1f})"
        )
        logger.info(f"  → max_pos={params.max_positions} "
                    f"max_pct={params.max_position_pct*100:.0f}% "
                    f"sides={params.allowed_sides} "
                    f"threshold={params.signal_threshold}")
        return params

    def is_side_allowed(self, side: str) -> bool:
        """Check if a trade side (long/short) is allowed in current regime."""
        regime = self.get_regime()
        return side.lower() in regime.allowed_sides
