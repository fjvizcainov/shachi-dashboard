"""
Claude Analyst — Phase 1

Claude Sonnet 4.6 with extended thinking + tool use.
Called 2-4x/day max. Every decision is high-conviction.

Flow:
  1. Pre-market (9:00 AM ET): day thesis + 2-3 conviction themes
  2. Signal trigger (mechanical screener fires): evaluate specific entry
  3. Mid-day review (12:00 PM ET): is thesis intact?
  4. Emergency (VIX spike / circuit breaker): reassess

Tools available to Claude during analysis:
  - get_live_price
  - get_ticker_news
  - get_technicals_snapshot
  - get_positions
  - get_market_regime
  - get_my_trade_history
  - get_sector_performance
  - get_top_signals (from mechanical screener)
"""

import json
import logging
import os
import time
import requests
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import anthropic

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import config
from data_sources.polygon_client import PolygonClient
from features.technical import TechnicalFeatures
from memory.trade_memory import trade_memory

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
#  Tool implementations — real data, no mocks                         #
# ------------------------------------------------------------------ #

_polygon = PolygonClient()
_features = TechnicalFeatures()


def _tool_get_live_price(ticker: str) -> Dict:
    """Get live price + 1h change for a ticker."""
    try:
        if "/" in ticker:
            symbols = ticker
            resp = requests.get(
                f"https://data.alpaca.markets/v1beta3/crypto/us/latest/bars?symbols={symbols}",
                headers={
                    "APCA-API-KEY-ID": config.alpaca.api_key,
                    "APCA-API-SECRET-KEY": config.alpaca.secret_key,
                },
                timeout=5,
            )
            if resp.status_code == 200:
                bar = resp.json().get("bars", {}).get(ticker, {})
                return {"ticker": ticker, "price": float(bar.get("c", 0)), "source": "alpaca_crypto"}
        else:
            resp = requests.get(
                f"https://data.alpaca.markets/v2/stocks/{ticker}/quotes/latest",
                headers={
                    "APCA-API-KEY-ID": config.alpaca.api_key,
                    "APCA-API-SECRET-KEY": config.alpaca.secret_key,
                },
                timeout=5,
            )
            if resp.status_code == 200:
                q = resp.json().get("quote", {})
                mid = (float(q.get("ap", 0)) + float(q.get("bp", 0))) / 2
                return {"ticker": ticker, "price": round(mid, 4), "ask": q.get("ap"), "bid": q.get("bp")}
    except Exception as e:
        logger.debug(f"live price error {ticker}: {e}")
    # Fallback: last bar from Polygon
    try:
        end = datetime.now()
        start = end - timedelta(hours=2)
        df = _polygon.get_aggregates(ticker, 1, "hour", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        if df is not None and not df.empty:
            return {"ticker": ticker, "price": round(float(df["close"].iloc[-1]), 4)}
    except Exception:
        pass
    return {"ticker": ticker, "price": 0, "error": "unavailable"}


def _tool_get_ticker_news(ticker: str, hours: int = 4) -> List[Dict]:
    """Get recent news headlines for a ticker."""
    try:
        since = (datetime.utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        resp = requests.get(
            "https://data.alpaca.markets/v1beta1/news",
            headers={
                "APCA-API-KEY-ID": config.alpaca.api_key,
                "APCA-API-SECRET-KEY": config.alpaca.secret_key,
            },
            params={"symbols": ticker, "start": since, "sort": "desc", "limit": 8},
            timeout=8,
        )
        if resp.status_code == 200:
            items = resp.json().get("news", [])
            return [
                {
                    "headline": item.get("headline", ""),
                    "source": item.get("source", ""),
                    "time": item.get("created_at", "")[:16],
                    "summary": item.get("summary", "")[:200],
                }
                for item in items
            ]
    except Exception as e:
        logger.debug(f"News error {ticker}: {e}")
    return []


def _tool_get_technicals_snapshot(ticker: str) -> Dict:
    """Get key technical indicators for a ticker plus live intraday volume from Alpaca."""
    try:
        end = datetime.now()
        start = end - timedelta(days=10)
        df = _polygon.get_aggregates(ticker, 1, "hour", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        if df is None or len(df) < 20:
            return {"error": "insufficient data"}
        df = _features.compute_all(df)
        latest = df.iloc[-1]

        def safe(v, d=0):
            try:
                f = float(v)
                return round(f, 4) if f == f else d
            except Exception:
                return d

        # Volume based on last closed hourly bar
        hist_vol_ratio = safe(latest.get("volume_ratio_20", 1), 1)

        # Live intraday volume from Alpaca (current partial bar)
        live_vol_ratio = None
        try:
            from config.settings import config as _cfg
            import requests as _req
            resp = _req.get(
                f"https://data.alpaca.markets/v2/stocks/{ticker}/bars",
                headers={
                    "APCA-API-KEY-ID": _cfg.alpaca.api_key,
                    "APCA-API-SECRET-KEY": _cfg.alpaca.secret_key,
                },
                params={"timeframe": "1Min", "limit": 30, "sort": "asc", "adjustment": "split"},
                timeout=5,
            )
            if resp.status_code == 200:
                bars_1m = resp.json().get("bars", [])
                if bars_1m:
                    current_hour_vol = sum(float(b.get("v", 0)) for b in bars_1m)
                    avg_hourly_vol = float(latest.get("volume_sma_20", safe(latest["volume"], 1)))
                    if avg_hourly_vol > 0:
                        live_vol_ratio = round(current_hour_vol / avg_hourly_vol, 2)
        except Exception:
            pass

        price_val = safe(latest["close"])
        sma20_val = safe(latest.get("sma_20", latest["close"]))
        stoch_k   = safe(latest.get("stoch_k", 50), 50)
        stoch_d   = safe(latest.get("stoch_d", 50), 50)
        williams_r = safe(latest.get("williams_r", -50), -50)
        bb_pct_b   = safe(latest.get("bb_pct_b", 0.5), 0.5)

        # Oscillator zone labels (contextual hints for Claude)
        stoch_zone = (
            "OVERBOUGHT" if stoch_k > 80 else
            "OVERSOLD"   if stoch_k < 20 else
            "NEUTRAL"
        )
        wr_zone = (
            "OVERBOUGHT" if williams_r > -20 else
            "OVERSOLD"   if williams_r < -80 else
            "NEUTRAL"
        )
        bb_zone = (
            "UPPER_BAND"  if bb_pct_b > 0.90 else
            "LOWER_BAND"  if bb_pct_b < 0.10 else
            "MID_UPPER"   if bb_pct_b > 0.60 else
            "MID_LOWER"   if bb_pct_b < 0.40 else
            "MIDDLE"
        )

        return {
            "ticker": ticker,
            "price": price_val,
            "rsi_14": safe(latest.get("rsi_14", 50), 50),
            "macd": safe(latest.get("macd", 0)),
            "macd_signal": safe(latest.get("macd_signal", 0)),
            "macd_hist": safe(latest.get("macd_histogram", 0)),
            "sma_20": sma20_val,
            "sma_50": safe(latest.get("sma_50", latest["close"])),
            "bb_pct_b": bb_pct_b,
            "bb_zone": bb_zone,
            "stoch_k": stoch_k,
            "stoch_d": stoch_d,
            "stoch_zone": stoch_zone,
            "williams_r": williams_r,
            "williams_r_zone": wr_zone,
            "atr_14": safe(latest.get("atr_14", 0)),
            "atr_14_pct": safe(latest.get("atr_14_pct", 0.01), 0.01),
            "adx": safe(latest.get("adx", 0)),
            "volume_ratio_prev_hour": hist_vol_ratio,
            "volume_ratio_live": live_vol_ratio,
            "trend_vs_sma20": "ABOVE" if price_val > sma20_val else "BELOW",
        }
    except Exception as e:
        return {"error": str(e)}


def _tool_get_positions(broker_session) -> List[Dict]:
    """Get current open positions from Alpaca."""
    try:
        resp = broker_session.get(
            f"{config.alpaca.base_url}/v2/positions",
            timeout=8,
        )
        if resp.status_code == 200:
            positions = resp.json()
            return [
                {
                    "symbol": p.get("symbol"),
                    "side": "LONG" if float(p.get("qty", 0)) > 0 else "SHORT",
                    "qty": abs(float(p.get("qty", 0))),
                    "entry_price": round(float(p.get("avg_entry_price", 0)), 4),
                    "current_price": round(float(p.get("current_price", 0)), 4),
                    "market_value": round(float(p.get("market_value", 0)), 2),
                    "unrealized_pnl": round(float(p.get("unrealized_pl", 0)), 2),
                    "unrealized_pnl_pct": round(float(p.get("unrealized_plpc", 0)) * 100, 2),
                }
                for p in positions
            ]
    except Exception as e:
        logger.debug(f"Positions error: {e}")
    return []


def _tool_get_market_regime() -> Dict:
    """Compute current macro regime: BULL/NEUTRAL/BEAR/HIGH_VOL/CRISIS."""
    try:
        end = datetime.now()
        start = end - timedelta(days=260)
        spy_df = _polygon.get_aggregates("SPY", 1, "day", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        if spy_df is None or len(spy_df) < 50:
            return {"regime": "UNKNOWN"}

        spy_df = _features.compute_all(spy_df)
        latest = spy_df.iloc[-1]
        price = float(latest["close"])
        sma200 = float(latest.get("sma_200", price) or price)
        rsi = float(latest.get("rsi_14", 50) or 50)

        # VIX from Polygon
        vix = 20.0
        try:
            vdf = _polygon.get_aggregates("VIX", 1, "day", (end - timedelta(days=5)).strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
            if vdf is not None and not vdf.empty:
                vix = float(vdf["close"].iloc[-1])
        except Exception:
            pass

        if vix > 40:
            regime = "CRISIS"
        elif vix > 28:
            regime = "HIGH_VOL"
        elif price < sma200 * 0.97:
            regime = "BEAR"
        elif price > sma200 * 1.02:
            regime = "BULL"
        else:
            regime = "NEUTRAL"

        spy_change_1d = round((float(spy_df["close"].iloc[-1]) / float(spy_df["close"].iloc[-2]) - 1) * 100, 2)
        spy_change_5d = round((float(spy_df["close"].iloc[-1]) / float(spy_df["close"].iloc[-5]) - 1) * 100, 2)

        return {
            "regime": regime,
            "spy_price": round(price, 2),
            "spy_sma200": round(sma200, 2),
            "spy_vs_sma200_pct": round((price / sma200 - 1) * 100, 2),
            "spy_rsi": round(rsi, 1),
            "spy_change_1d": spy_change_1d,
            "spy_change_5d": spy_change_5d,
            "vix": round(vix, 1),
            "max_exposure_pct": {"BULL": 90, "NEUTRAL": 60, "BEAR": 40, "HIGH_VOL": 30, "CRISIS": 0}.get(regime, 60),
        }
    except Exception as e:
        return {"regime": "UNKNOWN", "error": str(e)}


def _tool_get_my_trade_history(ticker: Optional[str] = None, days: int = 30) -> Dict:
    """Get our recent trade performance, optionally filtered by ticker."""
    try:
        since = (datetime.now() - timedelta(days=days)).isoformat()
        trades = list(trade_memory.trades.values())
        closed = [t for t in trades if getattr(t, "status", "") == "closed"]

        if ticker:
            closed = [t for t in closed if getattr(t, "ticker", "") == ticker]

        pnls = [float(getattr(t, "pnl_usd", 0) or 0) for t in closed]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        result = {
            "total_trades": len(pnls),
            "win_rate": round(len(wins) / len(pnls) * 100, 1) if pnls else 0,
            "total_pnl": round(sum(pnls), 2),
            "avg_win": round(sum(wins) / len(wins), 2) if wins else 0,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
        }
        if ticker:
            result["ticker"] = ticker
            result["recent_trades"] = [
                {
                    "action": getattr(t, "action", ""),
                    "entry": getattr(t, "entry_price", 0),
                    "exit": getattr(t, "exit_price", 0),
                    "pnl": round(float(getattr(t, "pnl_usd", 0) or 0), 2),
                    "hold_h": round(float(getattr(t, "hold_duration_hours", 0) or 0), 1),
                    "reason": getattr(t, "exit_reason", ""),
                }
                for t in closed[-5:]
            ]
        return result
    except Exception as e:
        return {"error": str(e)}


def _tool_get_sector_performance() -> Dict:
    """Get today's performance for each sector ETF."""
    sector_etfs = {
        "Technology": "XLK", "Energy": "XLE", "Healthcare": "XLV",
        "Financials": "XLF", "Consumer Staples": "XLP", "Utilities": "XLU",
        "Industrials": "XLI", "Materials": "XLB", "Real Estate": "XLRE",
        "Consumer Disc": "XLC", "Gold": "GLD", "Bonds": "TLT",
    }
    result = {}
    try:
        tickers = list(sector_etfs.values())
        resp = requests.get(
            f"https://data.alpaca.markets/v2/stocks/snapshots?symbols={','.join(tickers)}",
            headers={
                "APCA-API-KEY-ID": config.alpaca.api_key,
                "APCA-API-SECRET-KEY": config.alpaca.secret_key,
            },
            timeout=8,
        )
        if resp.status_code == 200:
            snapshots = resp.json()
            for sector, etf in sector_etfs.items():
                snap = snapshots.get(etf, {})
                change = float(snap.get("todaysChangePerc", 0) or 0)
                result[sector] = {"etf": etf, "change_pct": round(change, 2)}
    except Exception as e:
        logger.debug(f"Sector perf error: {e}")
    # Sort by performance
    sorted_result = dict(sorted(result.items(), key=lambda x: x[1].get("change_pct", 0), reverse=True))
    return sorted_result


# ------------------------------------------------------------------ #
#  Claude Analyst                                                      #
# ------------------------------------------------------------------ #

TOOL_DEFINITIONS = [
    {
        "name": "get_live_price",
        "description": "Get the current live market price for a stock or crypto ticker.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "e.g. 'NVDA', 'BTC/USD'"}
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_ticker_news",
        "description": "Get recent news headlines for a ticker from the past N hours.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "hours": {"type": "integer", "default": 4, "description": "How many hours back to search"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_technicals_snapshot",
        "description": "Get key technical indicators (RSI, MACD, ATR, Bollinger %B + zone, Stochastic %K/%D + zone, Williams %R + zone, ADX, volume) for a ticker.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"}
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_positions",
        "description": "Get all currently open positions with entry price, current PnL, and market value.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_market_regime",
        "description": "Get current macro regime (BULL/NEUTRAL/BEAR/HIGH_VOL/CRISIS), SPY vs SMA200, VIX level.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_my_trade_history",
        "description": "Get our own historical trade performance, optionally for a specific ticker.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Optional: filter by ticker"},
                "days": {"type": "integer", "default": 30},
            },
        },
    },
    {
        "name": "get_sector_performance",
        "description": "Get today's performance percentage for all major sector ETFs and commodities.",
        "input_schema": {"type": "object", "properties": {}},
    },
]

SYSTEM_PROMPT = """You are an active quantitative trader managing a $88,000 paper trading portfolio.

## Your Core Identity
You target 5-10 trades per day across the full market session. You are opportunistic but disciplined.
You are NOT a commentator. You are a decision-maker. Bracket orders manage your downside — your job is to find entries.

## Performance Context (our real history)
- EOD holds: 70% win rate, avg +$135/trade — your BEST strategy
- 2h-6h holds: 63% win rate, avg +$150/trade — excellent
- <30min trades: 16% win rate, avg -$79/trade — CATASTROPHIC, avoid
- Premature manual closes: 22% win rate, avg -$37 — the #1 cause of losses

## The Iron Laws (never violate)
1. NEVER close a position opened less than 2 hours ago unless halt/news shock >5%
2. NEVER short index ETFs (SPY/QQQ/IWM/DIA) while individual stock longs are open
3. NEVER trade tickers: SOLUSD, MRNA, AAOX, RBLX, CORT, PLU, PLYX, BRZE, AEHR, STAA
4. Brackets (TP/SL) manage risk — do NOT override them with manual closes for normal -1%/-2% moves
5. Max 6 simultaneous positions

## Decision Framework
For ENTRIES: Use tools to verify — price, news, technicals, sector, regime, our history.
A good entry needs at least 3 of these 4: (1) identifiable catalyst or momentum theme, (2) technical confirmation, (3) volume > 1.2x avg (preferred, not required), (4) regime allows it.
Confidence >= 65% required to TRADE. Between 65-75%: size smaller. Above 75%: size normally.
If confidence is below 65%, return NO_TRADE with a specific reason.

### LONG signals (direction=long)
Standard rules above apply. Catalyst = company news, sector momentum, earnings beat, etc.

### SHORT signals (direction=short)
For SHORT entries, minimum threshold is **2 of 4** criteria (not 3 of 4):
(1) Bearish catalyst OR macro regime (VIX >= 20 counts as macro catalyst — no stock-specific news required),
(2) Technical breakdown confirmation: price below SMA20 AND SMA50, OR MACD crossing below signal, OR RSI > 65 rolling over from overbought, OR BB %B < 0.2,
(3) Volume confirmation (elevated volume on down-moves preferred but NOT required),
(4) Regime allows shorts (NEUTRAL/BEAR/HIGH_VOL/CRISIS all allow shorts now).
Criteria (2) + (4) alone = valid short if technically clear. Criteria (1) + (2) = strong short.
When VIX >= 20, the macro environment IS a valid catalyst for shorting overextended or weak stocks.
Short signals fire `action: SHORT` — execute as a SELL order.
Confidence >= 60% required for shorts (not 65%).
HARD RULE for shorts: if live RSI < 25, return NO_TRADE — the stock is in capitulation/exhaustion and mean-reversion risk is extreme. Wait for a bounce before shorting.

### Oscillator interpretation (Stochastic, Williams %R, BB %B)
`get_technicals_snapshot` now returns `stoch_k`, `stoch_zone`, `williams_r`, `williams_r_zone`, `bb_pct_b`, `bb_zone`.

**Stochastic %K:**
- > 80 (OVERBOUGHT): prime exit zone for longs / entry for shorts — especially if K crossing below D
- < 20 (OVERSOLD): prime entry for longs / cover zone for shorts — especially if K crossing above D
- Divergence between stoch and price = early reversal warning

**Williams %R:**
- > -20 (OVERBOUGHT): confirms short setup, extra conviction when RSI also > 65
- < -80 (OVERSOLD): confirms long setup, extra conviction when RSI also < 35
- Both overbought (Williams > -20 AND RSI > 70) = extremely strong short confirmation
- Both oversold (Williams < -80 AND RSI < 30) = extremely strong long confirmation

**Bollinger %B:**
- > 0.90 (UPPER_BAND): price extended to upper band — mean-reversion risk, bearish for longs, good for shorts
- < 0.10 (LOWER_BAND): price at lower band — potential bounce, good for longs
- Combined with volume confirmation: upper band + high vol = breakout (not reversal); upper band + low vol = likely reversal

**RSI/price divergences (screener pre-computed):**
- `bullish_div=True`: price made lower low but RSI made higher low → hidden buying pressure → favor LONG
- `bearish_div=True`: price made higher high but RSI made lower high → hidden selling pressure → favor SHORT
- Divergences are strong leading indicators but require price confirmation before entry

**Multi-oscillator confluence rule:**
When 2 or more oscillators agree (e.g. RSI overbought + Williams overbought + BB upper band), this is HIGH-CONFIDENCE signal confirmation. Weight this more heavily than any single indicator.

### RSI and indicator divergence — CRITICAL RULE
The screener RSI/volume are computed from the LAST COMPLETED hourly bar (30-90 minutes stale).
Your live tools (get_technicals_snapshot) fetch current data.
**NEVER reject a signal for "data integrity failure" because screener RSI ≠ live RSI.**
The screener metrics are only used for initial scoring/filtering. For your actual analysis, ALWAYS use what your live tools return — ignore screener RSI, screener vol_ratio, etc. entirely.
In a high-VIX market, a 30-40 point RSI divergence between screener and live is NORMAL and expected.

IMPORTANT — volume context: volume ratios from the screener may be based on the full trading day average.
Early in the session (before 11 AM ET), intraday volume often appears low vs the full-day average — do NOT
reject solely because current volume is below 1.5x if momentum and technicals are strong.

For POSITION UPDATES: Default is HOLD. Only update TP upward on accelerating winners.
Only close if: fundamental event AFTER entry + hold > 2h + loss > -5%.

## Sizing Rules
- 80%+ confidence: 15-22% of equity per position
- 70-80% confidence: 10-15% of equity per position
- 65-70% confidence: 5-10% of equity per position
- Never more than 6 positions
- ATR-based stops: 2.5x ATR distance (not flat %)

## Output Format
Always return valid JSON matching the schema requested."""


class ClaudeAnalyst:
    """
    Claude Sonnet 4.6 with extended thinking + tool use.
    Each call gets fresh real-time data via tools.
    """

    def __init__(self, broker_session=None):
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY not set. Add it to .env file.\n"
                "Get your key at: https://console.anthropic.com"
            )
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = "claude-sonnet-4-6"
        self.broker_session = broker_session
        self._history_file = Path(__file__).parent.parent / "logs" / "claude_conversation_history.json"
        self._history_file.parent.mkdir(exist_ok=True)
        self.response_history: List[Dict] = self._load_history()
        logger.info(f"ClaudeAnalyst initialized — model={self.model}, history={len(self.response_history)} cycles")

    def _load_history(self) -> List[Dict]:
        if self._history_file.exists():
            try:
                with open(self._history_file) as f:
                    data = json.load(f)
                return data[-20:]  # Keep last 20 cycles
            except Exception:
                pass
        return []

    def _save_history(self, entry: Dict):
        self.response_history.append(entry)
        self.response_history = self.response_history[-20:]
        try:
            with open(self._history_file, "w") as f:
                json.dump(self.response_history, f, indent=2, default=str)
        except Exception as e:
            logger.warning(f"History save failed: {e}")

    def _dispatch_tool(self, tool_name: str, tool_input: Dict) -> Any:
        """Execute a tool call and return the result."""
        try:
            if tool_name == "get_live_price":
                return _tool_get_live_price(tool_input["ticker"])
            elif tool_name == "get_ticker_news":
                return _tool_get_ticker_news(tool_input["ticker"], tool_input.get("hours", 4))
            elif tool_name == "get_technicals_snapshot":
                return _tool_get_technicals_snapshot(tool_input["ticker"])
            elif tool_name == "get_positions":
                return _tool_get_positions(self.broker_session)
            elif tool_name == "get_market_regime":
                return _tool_get_market_regime()
            elif tool_name == "get_my_trade_history":
                return _tool_get_my_trade_history(
                    tool_input.get("ticker"), tool_input.get("days", 30)
                )
            elif tool_name == "get_sector_performance":
                return _tool_get_sector_performance()
            else:
                return {"error": f"Unknown tool: {tool_name}"}
        except Exception as e:
            logger.error(f"Tool error {tool_name}: {e}")
            return {"error": str(e)}

    def _run_with_tools(self, messages: List[Dict], max_iterations: int = 8) -> str:
        """
        Run Claude with tool use loop until it produces a final text response.
        Extended thinking enabled for deeper reasoning.
        """
        current_messages = list(messages)

        for iteration in range(max_iterations):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=16000,
                thinking={
                    "type": "enabled",
                    "budget_tokens": 10000,
                },
                system=SYSTEM_PROMPT,
                tools=TOOL_DEFINITIONS,
                messages=current_messages,
            )

            # Check if we need to handle tool calls
            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
            text_blocks = [b for b in response.content if b.type == "text"]

            if not tool_use_blocks:
                # Final response
                return " ".join(b.text for b in text_blocks)

            # Execute all tool calls
            tool_results = []
            for tool_block in tool_use_blocks:
                logger.info(f"  🔧 Tool: {tool_block.name}({json.dumps(tool_block.input)[:80]})")
                result = self._dispatch_tool(tool_block.name, tool_block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_block.id,
                    "content": json.dumps(result),
                })

            # Add assistant response + tool results to conversation
            current_messages.append({"role": "assistant", "content": response.content})
            current_messages.append({"role": "user", "content": tool_results})

        raise RuntimeError(f"Tool loop exceeded {max_iterations} iterations")

    # ------------------------------------------------------------------ #
    #  Main analysis methods                                               #
    # ------------------------------------------------------------------ #

    def premarket_analysis(self, live_positions: List[Dict], performance_context: str = None) -> Dict:
        """
        9:00 AM ET pre-market analysis.
        Returns: day thesis + 2-3 conviction themes + any pre-open orders.
        performance_context: optional weekly summary from PerformanceTracker (Phase 3).
        """
        logger.info("📊 Running pre-market analysis (extended thinking)...")
        history_summary = self._format_history_summary()
        positions_str = json.dumps(live_positions, indent=2) if live_positions else "No open positions"
        perf_block = f"\n{performance_context}\n" if performance_context else ""

        prompt = f"""
## Pre-Market Analysis — {datetime.now().strftime('%Y-%m-%d %H:%M ET')}
{perf_block}

Open positions heading into today:
{positions_str}

Recent decision history:
{history_summary}

Use your tools to:
1. Check market regime and overnight SPY/futures direction
2. Scan sector performance to identify today's rotation theme
3. Check news for any overnight catalysts
4. Evaluate existing positions: are their theses still intact?
5. Identify 1-3 high-conviction setups for today

Then return JSON:
{{
    "day_thesis": "One paragraph: what is today's macro theme and primary edge?",
    "regime": "BULL|NEUTRAL|BEAR|HIGH_VOL|CRISIS",
    "themes": ["theme1", "theme2"],
    "existing_positions_review": [{{"ticker": "X", "action": "HOLD|CLOSE", "reason": "..."}}],
    "target_entries": [
        {{
            "ticker": "SYMBOL",
            "action": "LONG|SHORT",
            "confidence": 0.0,
            "rationale": "Why NOW, what's the edge",
            "position_size_pct": 0.18,
            "stop_loss_pct": 0.045,
            "take_profit_pct": 0.10,
            "entry_price": 0.0,
            "time_horizon": "EOD|4h|2h"
        }}
    ],
    "avoid_tickers": [],
    "risk_notes": "Any special risk conditions today"
}}
"""
        try:
            raw = self._run_with_tools([{"role": "user", "content": prompt}])
            result = self._extract_json(raw)
            result["timestamp"] = datetime.now().isoformat()
            result["call_type"] = "premarket"
            self._save_history(result)
            logger.info(f"Pre-market done: regime={result.get('regime')} targets={len(result.get('target_entries', []))}")
            return result
        except Exception as e:
            logger.error(f"Pre-market analysis failed: {e}")
            return {"error": str(e), "target_entries": [], "existing_positions_review": []}

    def evaluate_signal(self, signal: Dict, live_positions: List[Dict]) -> Dict:
        """
        Evaluate a mechanical screener signal.
        Returns: TRADE or NO_TRADE with full rationale.
        """
        ticker = signal["ticker"]
        score = signal["score"]
        logger.info(f"🤔 Evaluating signal: {ticker} score={score:.1f} type={signal.get('signal_type','?')}")

        history_summary = self._format_history_summary()
        positions_str = json.dumps(live_positions, indent=2)
        n_positions = len(live_positions)

        direction = signal.get("direction", "long")
        direction_label = "SHORT (SELL)" if direction == "short" else "LONG (BUY)"
        direction_note = (
            "This is a BEARISH/SHORT signal. Evaluate it as a SELL entry. "
            "Apply the SHORT entry framework from the system prompt. "
            "If VIX > 25 or regime is BEAR/HIGH_VOL/CRISIS, that IS the catalyst — "
            "no stock-specific news required. Use live technicals (ignore screener RSI/vol). "
            "action MUST be 'SHORT'. Confidence >= 60% required (not 65%)."
            if direction == "short" else
            "This is a BULLISH/LONG signal. Evaluate it as a BUY entry. action must be 'LONG'."
        )

        prompt = f"""
## Signal Evaluation — {datetime.now().strftime('%H:%M ET')}

Mechanical screener flagged: **{ticker}** (score={score:.1f}, type={signal.get('signal_type','?')})
**Direction: {direction_label}** — {direction_note}
Pre-screened metrics (FOR CONTEXT ONLY — do NOT use for your analysis): RSI={signal.get('rsi',0):.0f}, vol_ratio={signal.get('vol_ratio',1):.1f}x, 1h_roc={signal.get('roc_1h',0):+.2f}%
⚠️ Screener RSI/vol are stale (last completed hourly bar). Use ONLY your live tool data for analysis. A mismatch is NEVER a rejection reason.
For SHORT signals specifically: if screener RSI was low (30-45) but live RSI is now high (65-80), this means the stock BOUNCED strongly after the screener flagged it. This is a BETTER short entry — you are selling an overbought bounce in a structurally broken stock. RSI > 65 live on a short signal = ideal entry zone, not a disqualifier.

Current positions ({n_positions}/6):
{positions_str}

Recent decision history:
{history_summary}

Use your tools to verify this is a genuine opportunity. Investigate:
1. Current live price (confirm it's still valid)
2. Recent news (catalyst or adverse news — for shorts, macro regime counts as catalyst)
3. Technical snapshot (confirm breakdown/breakout direction matches signal)
4. Market regime (does macro support this direction? VIX level?)
5. Our own history on this ticker
6. Sector performance (is the sector confirming the direction?)

Apply The Iron Laws strictly. Be skeptical but directionally aware — evaluate for {direction_label}.

Return JSON:
{{
    "decision": "TRADE|NO_TRADE",
    "confidence": 0.0,
    "action": "LONG|SHORT",
    "ticker": "{ticker}",
    "entry_price": 0.0,
    "position_size_pct": 0.0,
    "stop_loss_price": 0.0,
    "take_profit_price": 0.0,
    "stop_loss_pct": 0.0,
    "take_profit_pct": 0.0,
    "time_horizon": "EOD|4h|2h",
    "catalyst": "Specific reason this moves NOW",
    "reasoning": "Full thesis including what would invalidate it",
    "rejection_reason": "If NO_TRADE: why"
}}
"""
        try:
            raw = self._run_with_tools([{"role": "user", "content": prompt}])
            result = self._extract_json(raw)
            result["ticker"] = ticker
            result["timestamp"] = datetime.now().isoformat()
            result["call_type"] = "signal_eval"
            if result.get("decision") == "TRADE":
                self._save_history(result)
            logger.info(
                f"Signal eval: {ticker} → {result.get('decision')} "
                f"conf={result.get('confidence',0):.0%} "
                f"{'✅' if result.get('decision')=='TRADE' else '❌'}"
            )
            return result
        except Exception as e:
            logger.error(f"Signal eval failed {ticker}: {e}")
            return {"decision": "NO_TRADE", "rejection_reason": str(e), "ticker": ticker}

    def midday_review(self, live_positions: List[Dict]) -> Dict:
        """
        12:00 PM ET mid-day review.
        Are theses intact? Any position adjustments needed?
        """
        logger.info("🕛 Running mid-day review...")
        positions_str = json.dumps(live_positions, indent=2)

        prompt = f"""
## Mid-Day Review — {datetime.now().strftime('%H:%M ET')}

Current portfolio:
{positions_str}

Use your tools to:
1. Check positions that are near their stop-losses
2. Extend TP on positions that are accelerating (winning positions only)
3. Check for any new adverse news on held positions
4. Identify if any new high-conviction setups emerged since pre-market

Return JSON:
{{
    "position_updates": [
        {{
            "ticker": "SYMBOL",
            "action": "HOLD|CLOSE|EXTEND_TP",
            "new_take_profit_price": 0.0,
            "reason": "..."
        }}
    ],
    "new_entries": [],
    "market_update": "Brief current regime assessment"
}}
"""
        try:
            raw = self._run_with_tools([{"role": "user", "content": prompt}])
            result = self._extract_json(raw)
            result["timestamp"] = datetime.now().isoformat()
            result["call_type"] = "midday_review"
            self._save_history(result)
            return result
        except Exception as e:
            logger.error(f"Mid-day review failed: {e}")
            return {"position_updates": [], "new_entries": []}

    def emergency_review(self, trigger: str, live_positions: List[Dict]) -> Dict:
        """
        Emergency review triggered by VIX spike / circuit breaker / gap >5%.
        """
        logger.warning(f"🚨 Emergency review triggered: {trigger}")
        positions_str = json.dumps(live_positions, indent=2)

        prompt = f"""
## EMERGENCY REVIEW — {datetime.now().strftime('%H:%M ET')}
Trigger: {trigger}

Current positions:
{positions_str}

Use your tools to assess the situation NOW.
Determine if positions should be held or closed based on the emergency condition.
Be conservative — capital preservation over profit in emergencies.

Return JSON:
{{
    "severity": "LOW|MEDIUM|HIGH|CRITICAL",
    "action": "HOLD_ALL|CLOSE_RISKY|CLOSE_ALL",
    "positions_to_close": ["TICKER1", "TICKER2"],
    "reasoning": "Why this action",
    "resume_trading": true
}}
"""
        try:
            raw = self._run_with_tools([{"role": "user", "content": prompt}])
            result = self._extract_json(raw)
            result["timestamp"] = datetime.now().isoformat()
            result["call_type"] = "emergency"
            self._save_history(result)
            return result
        except Exception as e:
            logger.error(f"Emergency review failed: {e}")
            return {"severity": "UNKNOWN", "action": "HOLD_ALL", "positions_to_close": []}

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _format_history_summary(self) -> str:
        if not self.response_history:
            return "No previous decisions."
        recent = self.response_history[-5:]
        lines = []
        for h in recent:
            ts = h.get("timestamp", "")[:16]
            call_type = h.get("call_type", "?")
            if call_type == "signal_eval":
                lines.append(
                    f"[{ts}] SIGNAL {h.get('ticker')} → {h.get('decision')} "
                    f"conf={h.get('confidence',0):.0%}"
                )
            elif call_type == "premarket":
                entries = h.get("target_entries", [])
                lines.append(f"[{ts}] PREMARKET: {h.get('day_thesis','')[:80]}... ({len(entries)} targets)")
            elif call_type == "midday_review":
                updates = h.get("position_updates", [])
                lines.append(f"[{ts}] MIDDAY: {len(updates)} updates")
        return "\n".join(lines) if lines else "No recent decisions."

    def _extract_json(self, text: str) -> Dict:
        """Extract JSON from Claude's response text."""
        # Try direct parse
        try:
            return json.loads(text.strip())
        except Exception:
            pass
        # Find JSON block
        import re
        matches = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if matches:
            try:
                return json.loads(matches[0])
            except Exception:
                pass
        # Find bare JSON object
        brace_start = text.find("{")
        if brace_start != -1:
            depth = 0
            for i, c in enumerate(text[brace_start:], brace_start):
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[brace_start : i + 1])
                        except Exception:
                            break
        logger.warning(f"Could not parse JSON from Claude response: {text[:200]}")
        return {}
