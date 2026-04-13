"""
Kelly Criterion Position Sizer — Phase 2

Computes optimal position size using historical win/loss data.

Formula (Full Kelly):
  f* = (p * b - q) / b
  where:
    p = win rate
    b = avg_win / avg_loss (payoff ratio)
    q = 1 - p

We apply a safety fraction (0.50 = Half-Kelly) to account for
estimation error and parameter uncertainty.

The sizer queries the trade_history.json for per-ticker and
portfolio-wide statistics, then computes:
  1. Kelly fraction → optimal % of equity
  2. Capped by regime max_position_pct
  3. Capped by available buying power
  4. Converts to integer share count
"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)

MEMORY_DIR          = Path(__file__).parent.parent / "memory"
TRADE_HISTORY_PATH  = MEMORY_DIR / "trade_history.json"

KELLY_SAFETY_FRACTION = 0.50   # Half-Kelly
MIN_POSITION_PCT      = 0.10   # Never less than 10% (needed for 1% daily PNL target)
DEFAULT_WIN_RATE      = 0.55   # Conservative prior
DEFAULT_PAYOFF        = 1.5    # Conservative prior
MIN_SAMPLE_SIZE       = 10     # Minimum trades to trust per-ticker statistics
MIN_PORTFOLIO_WIN_RATE = 0.40  # If portfolio WR below this, use DEFAULT priors instead


class PositionSizer:
    """
    Kelly-based position sizer with per-ticker statistics.

    Usage:
        sizer = PositionSizer()
        qty, pct = sizer.size(
            ticker="NVDA",
            price=900.0,
            equity=88000.0,
            max_pct=0.22,
            atr_pct=0.015,
        )
    """

    def __init__(self):
        self._stats_cache: Dict[str, Dict] = {}
        self._portfolio_stats: Optional[Dict] = None

    # ─── Statistics ───────────────────────────────────────────────────────────

    def _load_trade_history(self) -> list:
        if not TRADE_HISTORY_PATH.exists():
            return []
        try:
            data = json.loads(TRADE_HISTORY_PATH.read_text())
            if isinstance(data, list):
                return data
            # trade_history.json is {"trades": {"id": {...}, ...}}
            if isinstance(data, dict):
                trades = data.get("trades", {})
                if isinstance(trades, dict):
                    return list(trades.values())
                if isinstance(trades, list):
                    return trades
            return []
        except Exception:
            return []

    def _calc_stats(self, trades: list, ticker: str = None) -> Dict:
        """
        Compute win rate and avg win/loss for a subset of trades.
        If ticker is None, uses all trades (portfolio-wide).
        """
        relevant = [
            t for t in trades
            if (ticker is None or t.get("ticker") == ticker)
            and t.get("pnl_usd") is not None
        ]

        if len(relevant) < MIN_SAMPLE_SIZE:
            return {
                "win_rate":   DEFAULT_WIN_RATE,
                "payoff":     DEFAULT_PAYOFF,
                "n":          len(relevant),
                "trusted":    False,
            }

        wins  = [t["pnl_usd"] for t in relevant if t["pnl_usd"] > 0]
        losses= [abs(t["pnl_usd"]) for t in relevant if t["pnl_usd"] < 0]

        win_rate  = len(wins) / len(relevant)
        avg_win   = sum(wins) / len(wins)   if wins   else 0.0
        avg_loss  = sum(losses) / len(losses) if losses else 1.0
        payoff    = avg_win / avg_loss if avg_loss > 0 else DEFAULT_PAYOFF

        return {
            "win_rate": win_rate,
            "payoff":   payoff,
            "n":        len(relevant),
            "trusted":  True,
            "avg_win":  avg_win,
            "avg_loss": avg_loss,
        }

    def _get_stats(self, ticker: str) -> Dict:
        """Return per-ticker stats if sufficient history, else portfolio stats.
        Falls back to DEFAULT priors if portfolio win rate is too low to be trusted."""
        trades = self._load_trade_history()

        # Per-ticker
        ticker_stats = self._calc_stats(trades, ticker=ticker)
        if ticker_stats["trusted"]:
            # Only use if win rate is reasonable
            if ticker_stats["win_rate"] >= MIN_PORTFOLIO_WIN_RATE:
                return ticker_stats

        # Portfolio-wide fallback
        if self._portfolio_stats is None:
            self._portfolio_stats = self._calc_stats(trades)

        port = self._portfolio_stats
        # If portfolio win rate is too low (contaminated by old bad trades), use defaults
        if port["win_rate"] < MIN_PORTFOLIO_WIN_RATE:
            logger.info(
                f"Portfolio WR={port['win_rate']:.0%} < {MIN_PORTFOLIO_WIN_RATE:.0%} floor — "
                f"using DEFAULT priors (WR={DEFAULT_WIN_RATE:.0%}, payoff={DEFAULT_PAYOFF}x)"
            )
            return {
                "win_rate": DEFAULT_WIN_RATE,
                "payoff":   DEFAULT_PAYOFF,
                "n":        port["n"],
                "trusted":  False,
            }

        return port

    # ─── Kelly Formula ────────────────────────────────────────────────────────

    def _kelly(self, win_rate: float, payoff: float) -> float:
        """
        Full Kelly fraction.
        Clamped to [0, 0.40] to prevent over-betting.
        """
        q = 1.0 - win_rate
        if payoff <= 0:
            return 0.0
        f = (win_rate * payoff - q) / payoff
        return max(0.0, min(0.40, f))

    def _adjusted_kelly(self, win_rate: float, payoff: float) -> float:
        """Half-Kelly with safety fraction."""
        return self._kelly(win_rate, payoff) * KELLY_SAFETY_FRACTION

    # ─── ATR-Adjusted Sizing ──────────────────────────────────────────────────

    def _atr_adjustment(self, atr_pct: float, base_pct: float) -> float:
        """
        Scale down position size when ATR is high (volatile instrument).
        Benchmark ATR: 1.5%. atr_pct is clamped to [0.005, 0.10] before use.
        """
        BENCHMARK_ATR = 0.015
        # Clamp to realistic range — prevents corrupted screener values (e.g. 1.0 = 100%)
        atr_pct = max(0.005, min(0.10, atr_pct))

        if not atr_pct or atr_pct <= 0:
            return base_pct

        ratio = atr_pct / BENCHMARK_ATR
        if ratio <= 1.0:
            return base_pct  # No penalty for calm instruments

        # Linear decay with higher floor: 2x ATR → 85%, 4x ATR → 65% (min)
        penalty = max(0.65, 1.0 - (ratio - 1.0) * 0.12)
        return base_pct * penalty

    # ─── Public API ───────────────────────────────────────────────────────────

    def size(
        self,
        ticker: str,
        price: float,
        equity: float,
        max_pct: float = 0.22,
        atr_pct: float = 0.015,
        buying_power: float = None,
    ) -> Tuple[int, float]:
        """
        Compute position size.

        Returns:
            (qty: int, pct_of_equity: float)
        """
        if price <= 0 or equity <= 0:
            return 1, 0.0

        stats = self._get_stats(ticker)
        kelly_pct = self._adjusted_kelly(stats["win_rate"], stats["payoff"])

        # Blend Kelly with a conservative floor
        blended_pct = max(MIN_POSITION_PCT, kelly_pct)

        # ATR adjustment
        blended_pct = self._atr_adjustment(atr_pct, blended_pct)

        # Cap by regime / hard limit
        blended_pct = min(blended_pct, max_pct)

        # Dollar amount
        dollar_size = equity * blended_pct

        # Cap by buying power
        if buying_power and buying_power > 0:
            dollar_size = min(dollar_size, buying_power * 0.95)

        qty = max(1, int(dollar_size / price))
        actual_pct = (qty * price) / equity

        logger.info(
            f"Kelly size {ticker}: "
            f"WR={stats['win_rate']:.0%} payoff={stats['payoff']:.2f} "
            f"kelly={kelly_pct:.1%} → {blended_pct:.1%} "
            f"→ {qty} shares @ ${price:.2f} "
            f"(${qty*price:,.0f} = {actual_pct:.1%} equity) "
            f"[n={stats['n']} trusted={stats['trusted']}]"
        )

        return qty, actual_pct

    def explain(self, ticker: str) -> str:
        """Return human-readable sizing rationale for a ticker."""
        stats = self._get_stats(ticker)
        kelly = self._kelly(stats["win_rate"], stats["payoff"])
        half  = kelly * KELLY_SAFETY_FRACTION

        lines = [
            f"Ticker: {ticker}",
            f"  Historical trades: {stats['n']} "
            f"({'trusted' if stats['trusted'] else 'using portfolio prior'})",
            f"  Win rate: {stats['win_rate']:.1%}",
            f"  Payoff ratio: {stats['payoff']:.2f}x",
            f"  Full Kelly: {kelly:.1%}",
            f"  Half-Kelly (applied): {half:.1%}",
        ]
        return "\n".join(lines)
