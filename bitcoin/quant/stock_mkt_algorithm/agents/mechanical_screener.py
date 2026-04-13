"""
Mechanical Signal Screener — Phase 1

Pure Python signal engine. No AI. Runs every 2 minutes.
Scores every ticker in the universe 0-10.
Fires a signal when score >= SIGNAL_THRESHOLD.

Scoring components:
  - Momentum   (price vs MA, ROC)
  - Volume     (vs 20-day average)
  - RSI        (overbought/oversold zones)
  - Oscillator (Stochastic %K, Williams %R, BB %B confirmation)
  - Trend      (ADX, MA alignment, MACD)
  - Breakout   (Bollinger squeeze, band expansion)
  - Divergence (RSI/price divergence bonus)

Portfolio monitoring:
  - monitor_positions(): proactive extreme-zone alerts on open positions
"""

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import config
from data_sources.polygon_client import PolygonClient
from features.technical import TechnicalFeatures

logger = logging.getLogger(__name__)

# Tickers destruction tested — never score these
PERMANENT_BLACKLIST = {
    'SOLUSD', 'MRNA', 'AAOX', 'RBLX', 'CORT', 'PLU', 'PLYX',
    'SOL/USD', 'BRZE', 'AEHR', 'STAA',
}

# Minimum score to trigger a Claude evaluation
SIGNAL_THRESHOLD = 6.0

# Always include these regardless of most-actives (ETFs, crypto, proven names)
CORE_UNIVERSE = [
    # Proven winners from our own history
    "USO", "GLD", "SLV", "DBC", "UNG",
    "MSFT", "META", "AMZN", "GOOGL", "NVDA", "AAPL",
    "PLTR", "TSLA", "AMD",
    # Sector ETFs (strong relative rotation signals)
    "XLE", "XLF", "XLV", "XLK", "XLI", "XLP", "XLU", "XLB",
    # Fixed income / macro
    "TLT", "HYG", "LQD",
    # Broad market + leveraged
    "SPY", "QQQ", "IWM", "TQQQ", "SQQQ", "SPXU", "SOXL", "SOXS",
    # Large-cap value
    "WMT", "COST", "JPM", "BAC", "V", "MA",
    "UNH", "LLY", "ABBV", "JNJ",
    "XOM", "CVX", "COP", "RYCEY",
    "NKE", "SBUX", "MCD",
    # Cloud / tech — common short targets in risk-off
    "NOW", "SNOW", "NET", "AKAM", "FICO", "DOCN",
    "FSLY", "PATH", "DDOG", "CRWD",
    # Healthcare
    "GH", "LH",
    # Financials / specialty
    "SEZL", "CLBT",
    # High-momentum mid caps
    "LUNR", "RKLB", "ASTS",
    "COIN", "HOOD",
    # Crypto (long-only)
    "BTC/USD", "ETH/USD",
]

# Dynamic universe settings
UNIVERSE_TOP_N   = 100   # Alpaca most-actives max is 100
BARS_LIMIT       = 200   # Hourly bars per ticker (~25 trading days)
UNIVERSE_TTL     = 1800  # Re-fetch most-actives every 30 min
PREFETCH_WORKERS = 20    # Parallel Alpaca bar requests


class MechanicalScreener:
    """
    Scores every ticker every 2 minutes.
    Signals fire when composite score >= SIGNAL_THRESHOLD.
    No AI involvement — pure math.
    """

    def __init__(self):
        self.data_client = PolygonClient()
        self.features = TechnicalFeatures()
        self._cache: Dict[str, Tuple[pd.DataFrame, float]] = {}  # ticker → (df, timestamp)
        self._cache_ttl = 300  # 5 min cache
        self._universe_cache: List[str] = []
        self._universe_ts: float = 0.0

    # ------------------------------------------------------------------ #
    #  Universe building                                                   #
    # ------------------------------------------------------------------ #

    def _fetch_most_actives(self, top: int = UNIVERSE_TOP_N) -> List[str]:
        """Fetch today's most-active stocks by volume from Alpaca screener API."""
        try:
            resp = requests.get(
                "https://data.alpaca.markets/v1beta1/screener/stocks/most-actives",
                headers={
                    "APCA-API-KEY-ID": config.alpaca.api_key,
                    "APCA-API-SECRET-KEY": config.alpaca.secret_key,
                },
                params={"by": "volume", "top": top},
                timeout=15,
            )
            if resp.status_code == 200:
                items = resp.json().get("most_actives", [])
                tickers = [item["symbol"] for item in items if "symbol" in item]
                logger.info(f"Alpaca most-actives: {len(tickers)} stocks fetched")
                return tickers
            else:
                logger.warning(f"Most-actives API returned {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.warning(f"Most-actives fetch failed: {e}")
        return []

    def _build_universe(self) -> List[str]:
        """
        Build the full scan universe.
        Combines Alpaca most-actives (dynamic) with CORE_UNIVERSE (static).
        Cached for UNIVERSE_TTL seconds to avoid hammering the API.
        """
        now = time.time()
        if self._universe_cache and now - self._universe_ts < UNIVERSE_TTL:
            return self._universe_cache

        dynamic = self._fetch_most_actives()

        # Merge: dynamic list first (volume-ranked), then CORE_UNIVERSE extras
        # dict.fromkeys preserves insertion order and deduplicates
        stocks = list(dict.fromkeys(
            t for t in (dynamic + CORE_UNIVERSE)
            if t not in PERMANENT_BLACKLIST and "/" not in t
        ))
        crypto = [t for t in CORE_UNIVERSE if "/" in t]
        universe = stocks + crypto

        self._universe_cache = universe
        self._universe_ts = now
        logger.info(f"Universe built: {len(stocks)} stocks + {len(crypto)} crypto = {len(universe)} total")
        return universe

    def _fetch_alpaca_bars_single(self, ticker: str, start_dt: str) -> Optional[pd.DataFrame]:
        """Fetch hourly bars for one ticker from Alpaca (no rate limit)."""
        try:
            resp = requests.get(
                f"https://data.alpaca.markets/v2/stocks/{ticker}/bars",
                headers={
                    "APCA-API-KEY-ID": config.alpaca.api_key,
                    "APCA-API-SECRET-KEY": config.alpaca.secret_key,
                },
                params={
                    "timeframe": "1Hour",
                    "start": start_dt,
                    "limit": BARS_LIMIT,
                    "sort": "asc",
                    "adjustment": "split",
                },
                timeout=15,
            )
            if resp.status_code != 200:
                return None
            bars = resp.json().get("bars", [])
            if len(bars) < 20:
                return None
            df = pd.DataFrame(bars)
            df = df.rename(columns={
                "t": "timestamp", "o": "open", "h": "high",
                "l": "low", "c": "close", "v": "volume", "vw": "vwap",
            })
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            return df.set_index("timestamp").sort_index()
        except Exception:
            return None

    def _prefetch_bars(self, tickers: List[str]) -> int:
        """
        Parallel-fetch hourly bars for stock tickers via Alpaca (no rate limit).
        Computes technical features and populates self._cache.
        Returns number of tickers successfully cached.
        """
        stock_tickers = [t for t in tickers if "/" not in t]
        now = time.time()
        to_fetch = [
            t for t in stock_tickers
            if t not in self._cache or now - self._cache[t][1] >= self._cache_ttl
        ]
        if not to_fetch:
            return 0

        start_dt = (datetime.now() - timedelta(days=20)).strftime("%Y-%m-%dT00:00:00Z")
        cached_count = 0

        def _fetch_and_cache(ticker):
            df = self._fetch_alpaca_bars_single(ticker, start_dt)
            if df is None:
                return False
            try:
                df = self.features.compute_all(df)
                self._cache[ticker] = (df, time.time())
                return True
            except Exception:
                return False

        with ThreadPoolExecutor(max_workers=PREFETCH_WORKERS) as executor:
            futures = {executor.submit(_fetch_and_cache, t): t for t in to_fetch}
            for future in as_completed(futures):
                try:
                    if future.result(timeout=20):
                        cached_count += 1
                except Exception:
                    pass

        logger.info(f"Pre-fetched bars: {cached_count}/{len(to_fetch)} tickers cached via Alpaca")
        return cached_count

    # ------------------------------------------------------------------ #
    #  Data helpers                                                        #
    # ------------------------------------------------------------------ #

    def _get_ticker_df(self, ticker: str) -> Optional[pd.DataFrame]:
        """Fetch and cache hourly OHLCV + indicators."""
        now = time.time()
        if ticker in self._cache:
            df, ts = self._cache[ticker]
            if now - ts < self._cache_ttl:
                return df

        try:
            end = datetime.now()
            start = end - timedelta(days=10)
            df = self.data_client.get_aggregates(
                ticker=ticker, multiplier=1, timespan="hour",
                from_date=start.strftime("%Y-%m-%d"),
                to_date=end.strftime("%Y-%m-%d"),
            )
            if df is None or len(df) < 20:
                return None
            df = self.features.compute_all(df)
            self._cache[ticker] = (df, now)
            return df
        except Exception as e:
            logger.debug(f"Data error {ticker}: {e}")
            return None

    def _get_crypto_price(self, symbol: str) -> Optional[float]:
        """Get latest price for a crypto symbol."""
        try:
            api_key = config.alpaca.api_key
            secret_key = config.alpaca.secret_key
            url = f"https://data.alpaca.markets/v1beta3/crypto/us/latest/bars?symbols={symbol}"
            resp = requests.get(
                url,
                headers={"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret_key},
                timeout=5,
            )
            if resp.status_code == 200:
                bars = resp.json().get("bars", {})
                bar = bars.get(symbol, {})
                return float(bar.get("c", 0)) or None
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------ #
    #  Divergence detection                                               #
    # ------------------------------------------------------------------ #

    def _detect_divergence(self, df: pd.DataFrame, lookback: int = 20) -> Dict:
        """
        Detect RSI/price divergence in the last `lookback` bars.

        Bullish divergence: price makes a lower low, but RSI makes a higher low
          → hidden buying pressure, likely reversal up.
        Bearish divergence: price makes a higher high, but RSI makes a lower high
          → hidden selling pressure, likely reversal down.

        Returns dict with 'bullish_div' and 'bearish_div' booleans.
        Requires at least 2 pivot points to confirm (avoids noise).
        """
        result = {"bullish_div": False, "bearish_div": False}
        if len(df) < lookback + 4:
            return result

        window = df.iloc[-(lookback + 2):]
        closes = window["close"].values
        rsi_col = "rsi_14"
        rsi_vals = window[rsi_col].fillna(50).values if rsi_col in window.columns else [50] * len(closes)

        # Find pivot lows and highs (2-bar confirmation on each side)
        pivot_lows: list  = []
        pivot_highs: list = []
        for i in range(2, len(closes) - 2):
            is_low  = closes[i] < closes[i-1] and closes[i] < closes[i-2] and closes[i] < closes[i+1] and closes[i] < closes[i+2]
            is_high = closes[i] > closes[i-1] and closes[i] > closes[i-2] and closes[i] > closes[i+1] and closes[i] > closes[i+2]
            if is_low:
                pivot_lows.append((i, float(closes[i]), float(rsi_vals[i])))
            if is_high:
                pivot_highs.append((i, float(closes[i]), float(rsi_vals[i])))

        # Bullish div: more recent price low < prior low, but RSI higher (>2pt noise filter)
        if len(pivot_lows) >= 2:
            prior, recent = pivot_lows[-2], pivot_lows[-1]
            if recent[1] < prior[1] and recent[2] > prior[2] + 2.0:
                result["bullish_div"] = True

        # Bearish div: more recent price high > prior high, but RSI lower (>2pt noise filter)
        if len(pivot_highs) >= 2:
            prior, recent = pivot_highs[-2], pivot_highs[-1]
            if recent[1] > prior[1] and recent[2] < prior[2] - 2.0:
                result["bearish_div"] = True

        return result

    # ------------------------------------------------------------------ #
    #  Portfolio position monitoring                                       #
    # ------------------------------------------------------------------ #

    def monitor_positions(self, tickers: List[str]) -> List[Dict]:
        """
        Proactively check open position tickers for oscillator extremes and
        RSI/price divergences. Called after each screener cycle.

        Returns list of alert dicts for any ticker in an extreme zone.
        All alerts are also emitted as WARNING log messages.
        """
        alerts = []
        for ticker in tickers:
            if "/" in ticker or ticker in PERMANENT_BLACKLIST:
                continue
            df = self._get_ticker_df(ticker)
            if df is None or len(df) < 20:
                continue

            latest = df.iloc[-1]
            price      = float(latest["close"])
            rsi        = float(latest.get("rsi_14", 50) or 50)
            stoch_k    = float(latest.get("stoch_k", 50) or 50)
            stoch_d    = float(latest.get("stoch_d", 50) or 50)
            williams_r = float(latest.get("williams_r", -50) or -50)
            bb_pct_b   = float(latest.get("bb_pct_b", 0.5) or 0.5)
            divergence = self._detect_divergence(df)

            flags: List[str] = []

            # RSI extremes
            if rsi > 75:
                flags.append(f"RSI={rsi:.0f} OVERBOUGHT")
            elif rsi < 25:
                flags.append(f"RSI={rsi:.0f} OVERSOLD")

            # Stochastic extremes
            if stoch_k > 85:
                flags.append(f"Stoch-K={stoch_k:.0f} OVERBOUGHT")
            elif stoch_k < 15:
                flags.append(f"Stoch-K={stoch_k:.0f} OVERSOLD")

            # Williams %R extremes
            if williams_r > -10:
                flags.append(f"Williams%%R={williams_r:.0f} OVERBOUGHT")
            elif williams_r < -90:
                flags.append(f"Williams%%R={williams_r:.0f} OVERSOLD")

            # Bollinger band extremes
            if bb_pct_b > 0.95:
                flags.append(f"BB%%B={bb_pct_b:.2f} UPPER_BAND")
            elif bb_pct_b < 0.05:
                flags.append(f"BB%%B={bb_pct_b:.2f} LOWER_BAND")

            # Divergences
            if divergence["bullish_div"]:
                flags.append("BULLISH_DIVERGENCE (RSI rising while price falling)")
            if divergence["bearish_div"]:
                flags.append("BEARISH_DIVERGENCE (RSI falling while price rising)")

            if not flags:
                continue

            alert = {
                "ticker": ticker,
                "price": round(price, 4),
                "rsi": round(rsi, 1),
                "stoch_k": round(stoch_k, 1),
                "stoch_d": round(stoch_d, 1),
                "williams_r": round(williams_r, 1),
                "bb_pct_b": round(bb_pct_b, 3),
                "bullish_div": divergence["bullish_div"],
                "bearish_div": divergence["bearish_div"],
                "alerts": flags,
            }
            alerts.append(alert)
            logger.warning(
                f"⚠️  POSITION ALERT {ticker} @ ${price:.2f}: " + " | ".join(flags)
            )

        return alerts

    # ------------------------------------------------------------------ #
    #  Scoring                                                             #
    # ------------------------------------------------------------------ #

    def score_ticker(self, ticker: str) -> Dict:
        """
        Score a single ticker for both long AND short setups (0-10 each).
        Returns the stronger of the two signals with a 'direction' field.
        'direction' = 'long' or 'short' so the rest of the pipeline knows
        which side Claude should evaluate.
        """
        if ticker in PERMANENT_BLACKLIST:
            return {"ticker": ticker, "score": 0.0, "skip": True}

        # Crypto handled separately (long-only)
        if "/" in ticker:
            return self._score_crypto(ticker)

        df = self._get_ticker_df(ticker)
        if df is None or len(df) < 30:
            return {"ticker": ticker, "score": 0.0, "skip": True}

        latest = df.iloc[-1]
        prev = df.iloc[-2]
        price = float(latest["close"])
        if price < 5.0:
            return {"ticker": ticker, "score": 0.0, "skip": True}

        # Shared indicators
        roc_1h = (price / float(prev["close"]) - 1) * 100
        roc_5h = float(latest.get("roc_5", 0) or 0)
        sma20  = float(latest.get("sma_20", price) or price)
        sma50  = float(latest.get("sma_50", price) or price)
        vol    = float(latest.get("volume", 0) or 0)
        vol_avg= float(latest.get("volume_sma_20", vol) or vol)
        vol_ratio = vol / vol_avg if vol_avg > 0 else 1.0
        rsi    = float(latest.get("rsi_14", 50) or 50)
        adx    = float(latest.get("adx", 0) or 0)
        macd   = float(latest.get("macd", 0) or 0)
        macd_signal = float(latest.get("macd_signal", 0) or 0)
        bb_pct_b  = float(latest.get("bb_pct_b", 0.5) or 0.5)
        bb_squeeze= int(latest.get("bb_squeeze", 0) or 0)
        atr_pct   = round(max(0.005, min(0.10, float(latest.get("atr_14_pct", 0.015) or 0.015))), 4)
        stoch_k   = float(latest.get("stoch_k", 50) or 50)
        stoch_d   = float(latest.get("stoch_d", 50) or 50)
        stoch_cross = int(latest.get("stoch_cross", 0) or 0)  # 1=bullish, -1=bearish
        williams_r  = float(latest.get("williams_r", -50) or -50)

        # RSI/price divergence over last 20 bars
        divergence = self._detect_divergence(df)

        # ── LONG SCORING ──────────────────────────────────────────────────
        long_score = 0.0
        long_components = {}

        # 1. Momentum (0-3 pts)
        mom = 0.0
        if roc_1h > 1.0:   mom += 1.5
        elif roc_1h > 0.5: mom += 1.0
        if roc_5h > 3.0:   mom += 1.5
        elif roc_5h > 1.5: mom += 1.0
        if price > sma20 and price > sma50: mom += 1.0
        elif price > sma20:                 mom += 0.5
        long_score += min(3.0, mom)
        long_components["momentum"] = round(min(3.0, mom), 2)

        # 2. Volume (0-2 pts)
        vs = 0.0
        if vol_ratio > 1.5: vs = 1.0
        if vol_ratio > 2.5: vs = 2.0
        long_score += vs
        long_components["volume"] = round(vs, 2)

        # 3. RSI (0-2 pts)
        rs = 0.0
        if 40 <= rsi <= 60:                 rs = 1.0   # Neutral — room to run
        elif rsi < 35:                      rs = 2.0   # Oversold bounce
        elif rsi > 65 and vol_ratio > 1.5: rs = 1.5   # Strong breakout
        long_score += rs
        long_components["rsi"] = round(rs, 2)

        # 4. Trend (0-2 pts)
        ts = 0.0
        if adx > 25: ts += 1.0
        if adx > 35: ts += 0.5
        if macd > macd_signal: ts += 0.5
        long_score += min(2.0, ts)
        long_components["trend"] = round(min(2.0, ts), 2)

        # 5. Breakout bonus (0-1 pt)
        bs = 0.0
        if bb_squeeze and roc_1h > 0.3:         bs = 1.0
        elif bb_pct_b > 0.8 and vol_ratio > 1.5: bs = 0.5
        long_score += bs
        long_components["breakout"] = round(bs, 2)

        # 6. Oscillator confirmation (0-1 pt): Stochastic + Williams %R + BB%B
        osc = 0.0
        if stoch_k < 20 and stoch_cross >= 0:   osc += 0.5   # Stoch oversold + turning up
        elif stoch_k < 30:                       osc += 0.3   # Stoch oversold
        if williams_r < -80:                     osc += 0.3   # Williams oversold
        if bb_pct_b < 0.15:                      osc += 0.2   # Near lower Bollinger band
        osc = round(min(1.0, osc), 2)
        long_score += osc
        long_components["oscillator"] = osc

        # 7. Divergence bonus (+0.5 pt for confirmed bullish RSI/price divergence)
        if divergence["bullish_div"]:
            long_score += 0.5
            long_components["divergence"] = 0.5

        long_score = round(min(10.0, long_score), 2)

        # Determine long signal type
        long_type = "MOMENTUM"
        if rsi < 35 and roc_1h > 0:             long_type = "OVERSOLD_BOUNCE"
        elif bb_squeeze:                         long_type = "SQUEEZE_BREAKOUT"
        elif roc_5h > 3.0 and vol_ratio > 2.0:  long_type = "VOLUME_SURGE"
        elif divergence["bullish_div"]:          long_type = "BULLISH_DIVERGENCE"

        # ── SHORT SCORING ─────────────────────────────────────────────────
        short_score = 0.0
        short_components = {}

        # 1. Bearish momentum (0-3 pts) — mirror of long momentum
        bmom = 0.0
        if roc_1h < -1.0:   bmom += 1.5
        elif roc_1h < -0.5: bmom += 1.0
        if roc_5h < -3.0:   bmom += 1.5
        elif roc_5h < -1.5: bmom += 1.0
        # Price below key MAs
        if price < sma20 and price < sma50: bmom += 1.0
        elif price < sma20:                 bmom += 0.5
        short_score += min(3.0, bmom)
        short_components["momentum"] = round(min(3.0, bmom), 2)

        # 2. Volume on down-move (0-2 pts) — same logic; volume confirms selling
        short_score += vs
        short_components["volume"] = round(vs, 2)

        # 3. RSI positioning for short (0-2 pts)
        # RSI < 25 = capitulation/exhaustion — do NOT short here (mean-reversion risk)
        rs_short = 0.0
        if rsi > 70:                        rs_short = 2.0   # Overbought — prime short zone
        elif 60 < rsi <= 70:               rs_short = 1.5   # Extended — sell the strength
        elif 40 <= rsi <= 60:              rs_short = 1.0   # Neutral — room to fall
        elif 25 <= rsi < 40 and roc_1h < 0: rs_short = 0.5 # Falling but not exhausted
        # rsi < 25: score 0 — too oversold, do not short into capitulation
        short_score += rs_short
        short_components["rsi"] = round(rs_short, 2)

        # 4. Bearish trend (0-2 pts)
        bts = 0.0
        if adx > 25: bts += 1.0
        if adx > 35: bts += 0.5
        if macd < macd_signal: bts += 0.5   # MACD bearish cross
        short_score += min(2.0, bts)
        short_components["trend"] = round(min(2.0, bts), 2)

        # 5. Breakdown bonus (0-1 pt) — mirror of breakout
        bbs = 0.0
        if bb_squeeze and roc_1h < -0.3:          bbs = 1.0   # Squeeze resolving down
        elif bb_pct_b < 0.2 and vol_ratio > 1.5: bbs = 0.5   # Lower band expansion
        short_score += bbs
        short_components["breakdown"] = round(bbs, 2)

        # 6. Oscillator confirmation (0-1 pt): Stochastic + Williams %R + BB%B
        osc_s = 0.0
        if stoch_k > 80 and stoch_cross <= 0:    osc_s += 0.5   # Stoch overbought + turning down
        elif stoch_k > 70:                        osc_s += 0.3   # Stoch overbought
        if williams_r > -20:                      osc_s += 0.3   # Williams overbought
        if bb_pct_b > 0.85:                       osc_s += 0.2   # Near upper Bollinger band
        osc_s = round(min(1.0, osc_s), 2)
        short_score += osc_s
        short_components["oscillator"] = osc_s

        # 7. Divergence bonus (+0.5 pt for confirmed bearish RSI/price divergence)
        if divergence["bearish_div"]:
            short_score += 0.5
            short_components["divergence"] = 0.5

        # Hard block: RSI < 25 = capitulation zone, do not short
        if rsi < 25:
            short_score = 0.0

        short_score = round(min(10.0, short_score), 2)

        # Determine short signal type
        short_type = "BEARISH_MOMENTUM"
        if rsi > 70 and roc_1h < 0:              short_type = "OVERBOUGHT_REVERSAL"
        elif bb_squeeze and roc_1h < -0.3:       short_type = "SQUEEZE_BREAKDOWN"
        elif roc_5h < -3.0 and vol_ratio > 2.0:  short_type = "DISTRIBUTION"
        elif divergence["bearish_div"]:           short_type = "BEARISH_DIVERGENCE"

        # ── RETURN THE STRONGER SIGNAL ────────────────────────────────────
        # Tie goes to long (shorting requires higher conviction)
        _common = {
            "rsi": round(rsi, 1),
            "stoch_k": round(stoch_k, 1),
            "stoch_d": round(stoch_d, 1),
            "williams_r": round(williams_r, 1),
            "bb_pct_b": round(bb_pct_b, 3),
            "roc_1h": round(roc_1h, 3),
            "roc_5h": round(roc_5h, 3),
            "vol_ratio": round(vol_ratio, 2),
            "adx": round(adx, 1),
            "atr_pct": atr_pct,
            "sma_20": round(sma20, 4),
            "sma_50": round(sma50, 4),
            "macd": round(macd, 4),
            "macd_signal": round(macd_signal, 4),
            "bullish_div": divergence["bullish_div"],
            "bearish_div": divergence["bearish_div"],
        }

        if short_score > long_score and short_score >= SIGNAL_THRESHOLD:
            return {
                "ticker": ticker,
                "score": short_score,
                "price": round(price, 4),
                "signal_type": short_type,
                "direction": "short",
                "components": short_components,
                **_common,
            }

        return {
            "ticker": ticker,
            "score": long_score,
            "price": round(price, 4),
            "signal_type": long_type,
            "direction": "long",
            "components": long_components,
            **_common,
        }

    def _score_crypto(self, symbol: str) -> Dict:
        """Score a crypto asset (long-only, uses Alpaca bars)."""
        try:
            api_key = config.alpaca.api_key
            secret_key = config.alpaca.secret_key
            url = f"https://data.alpaca.markets/v1beta3/crypto/us/bars?symbols={symbol}&timeframe=1H&limit=48&sort=asc"
            resp = requests.get(
                url,
                headers={"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret_key},
                timeout=8,
            )
            if resp.status_code != 200:
                return {"ticker": symbol, "score": 0.0, "skip": True}

            bars = resp.json().get("bars", {}).get(symbol, [])
            if len(bars) < 20:
                return {"ticker": symbol, "score": 0.0, "skip": True}

            closes = [float(b["c"]) for b in bars]
            volumes = [float(b["v"]) for b in bars]
            price = closes[-1]

            sma20 = sum(closes[-20:]) / 20
            sma5 = sum(closes[-5:]) / 5
            roc_4h = (closes[-1] / closes[-4] - 1) * 100 if len(closes) >= 4 else 0
            roc_24h = (closes[-1] / closes[-24] - 1) * 100 if len(closes) >= 24 else 0
            vol_ratio = volumes[-1] / (sum(volumes[-20:]) / 20) if volumes else 1.0

            # RSI
            gains = [max(0, closes[i] - closes[i-1]) for i in range(-14, 0)]
            losses = [max(0, closes[i-1] - closes[i]) for i in range(-14, 0)]
            avg_gain = sum(gains) / 14
            avg_loss = sum(losses) / 14 + 1e-10
            rsi = 100 - 100 / (1 + avg_gain / avg_loss)

            score = 0.0
            # Long-only: only score if uptrend
            if roc_4h > 1.0: score += 2.0
            elif roc_4h > 0.5: score += 1.0
            if roc_24h > 3.0: score += 2.0
            elif roc_24h > 1.5: score += 1.0
            if price > sma20: score += 2.0
            if sma5 > sma20: score += 1.0
            if 40 < rsi < 65: score += 1.0
            if vol_ratio > 1.5: score += 1.0
            if vol_ratio > 2.5: score += 1.0

            return {
                "ticker": symbol,
                "score": round(min(10.0, score), 2),
                "price": round(price, 2),
                "signal_type": "CRYPTO_MOMENTUM",
                "rsi": round(rsi, 1),
                "roc_1h": round(roc_4h / 4, 3),
                "roc_5h": round(roc_4h, 3),
                "vol_ratio": round(vol_ratio, 2),
                "atr_pct": 1.5,
                "components": {"momentum": min(4.0, score), "volume": min(2.0, vol_ratio - 1)},
            }
        except Exception as e:
            logger.debug(f"Crypto score error {symbol}: {e}")
            return {"ticker": symbol, "score": 0.0, "skip": True}

    # ------------------------------------------------------------------ #
    #  Universe scan                                                       #
    # ------------------------------------------------------------------ #

    def scan(self, universe: Optional[List[str]] = None) -> List[Dict]:
        """
        Scan the full universe. Returns all signals sorted by score desc.
        Signals with score >= SIGNAL_THRESHOLD are flagged for Claude.

        When universe is None, automatically builds a dynamic universe from
        Alpaca's most-actives screener (~500 stocks) + CORE_UNIVERSE.
        Bars are batch-fetched via Alpaca multi-stock API before scoring,
        avoiding per-ticker Polygon rate limits.
        """
        if universe is not None:
            tickers = [t for t in universe if t not in PERMANENT_BLACKLIST]
        else:
            tickers = self._build_universe()

        # Batch pre-fetch bars for all stocks via Alpaca (one call per 100 tickers)
        stock_tickers = [t for t in tickers if "/" not in t]
        self._prefetch_bars(stock_tickers)

        results = []

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(self.score_ticker, t): t for t in tickers}
            for future in as_completed(futures):
                try:
                    result = future.result(timeout=15)
                    if not result.get("skip") and result["score"] > 0:
                        results.append(result)
                except Exception:
                    pass

        results.sort(key=lambda x: x["score"], reverse=True)
        signals = [r for r in results if r["score"] >= SIGNAL_THRESHOLD]

        logger.info(
            f"Screener: {len(tickers)} universe, {len(results)} scored, "
            f"{len(signals)} signals >= {SIGNAL_THRESHOLD}"
        )
        if signals:
            for s in signals[:5]:
                direction = s.get("direction", "long")
                arrow = "▲" if direction == "long" else "▼"
                logger.info(
                    f"  {arrow} {s['ticker']:10} score={s['score']:.1f} "
                    f"[{direction.upper()}] type={s.get('signal_type','?')} "
                    f"rsi={s.get('rsi',0):.0f} "
                    f"vol={s.get('vol_ratio',1):.1f}x price=${s.get('price',0):.2f}"
                )

        return results  # Full list; caller filters by score

    def get_top_signals(self, n: int = 5, universe: Optional[List[str]] = None) -> List[Dict]:
        """Return top N signals above threshold."""
        all_scored = self.scan(universe)
        return [s for s in all_scored if s["score"] >= SIGNAL_THRESHOLD][:n]
