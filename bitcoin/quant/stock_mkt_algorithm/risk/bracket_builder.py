"""
ATR-Based Bracket Builder — Phase 2

Computes stop-loss and take-profit prices using Average True Range
rather than flat percentages.

Rationale:
  - Flat 2% stops are too tight on volatile instruments (NVDA, TSLA)
    and too loose on calm ones (KO, JNJ)
  - ATR naturally adapts to each instrument's volatility regime
  - Stop = entry ± ATR_STOP_MULT × ATR14
  - Target = entry ± ATR_TP_MULT × ATR14

R:R = ATR_TP_MULT / ATR_STOP_MULT = 4 / 2.5 = 1.6
(minimum acceptable R:R for positive expectancy with 40%+ win rate)

For crypto (wider ATR), multipliers are slightly looser.
"""

import logging
from dataclasses import dataclass
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Equity multipliers
ATR_STOP_MULT    = 2.5
ATR_TP_MULT      = 4.0

# Crypto multipliers (wider stops needed due to volatility)
ATR_STOP_MULT_CRYPTO = 3.0
ATR_TP_MULT_CRYPTO   = 5.0

# Hard-floor stop as % of price (safety net for illiquid hours)
MIN_STOP_PCT = 0.008   # 0.8% minimum distance
MAX_STOP_PCT = 0.08    # 8% maximum stop distance (never wider)


@dataclass
class Bracket:
    """Entry bracket: stop-loss + take-profit levels."""
    entry:      float
    stop_loss:  float
    take_profit:float
    stop_dist:  float   # absolute distance to stop
    tp_dist:    float   # absolute distance to target
    rr_ratio:   float   # reward:risk ratio
    atr:        float   # ATR value used
    side:       str     # "long" or "short"


class BracketBuilder:
    """
    Builds ATR-calibrated bracket orders.

    Usage:
        builder = BracketBuilder()
        bracket = builder.build(
            ticker="NVDA",
            entry=900.0,
            atr_pct=0.018,   # ATR as % of price
            side="long",
        )
    """

    def build(
        self,
        ticker: str,
        entry: float,
        atr_pct: float,
        side: str = "long",
        is_crypto: bool = False,
    ) -> Bracket:
        """
        Compute stop-loss and take-profit for a bracket order.

        Args:
            ticker:     Ticker symbol (for logging)
            entry:      Entry price
            atr_pct:    ATR as fraction of price (e.g. 0.015 = 1.5%)
            side:       "long" or "short"
            is_crypto:  Use wider multipliers for crypto

        Returns:
            Bracket dataclass with rounded prices
        """
        is_long = side.lower() == "long"

        stop_mult = ATR_STOP_MULT_CRYPTO if is_crypto else ATR_STOP_MULT
        tp_mult   = ATR_TP_MULT_CRYPTO   if is_crypto else ATR_TP_MULT

        # Clamp atr_pct to reasonable range before any calculation
        atr_pct   = max(0.005, min(0.10, atr_pct))

        atr       = entry * atr_pct
        stop_dist = entry * max(MIN_STOP_PCT, min(MAX_STOP_PCT, atr_pct * stop_mult))
        tp_dist   = entry * atr_pct * tp_mult

        # Ensure minimum TP > stop (R:R > 1)
        tp_dist = max(tp_dist, stop_dist * 1.5)

        if is_long:
            stop_loss   = round(entry - stop_dist, 4)
            take_profit = round(entry + tp_dist,   4)
        else:
            stop_loss   = round(entry + stop_dist, 4)
            take_profit = round(entry - tp_dist,   4)

        rr = tp_dist / stop_dist if stop_dist > 0 else 0.0

        bracket = Bracket(
            entry=round(entry, 4),
            stop_loss=stop_loss,
            take_profit=take_profit,
            stop_dist=round(stop_dist, 4),
            tp_dist=round(tp_dist, 4),
            rr_ratio=round(rr, 2),
            atr=round(atr, 4),
            side=side.lower(),
        )

        logger.info(
            f"Bracket {ticker} {side.upper()}: "
            f"entry=${entry:.2f} "
            f"SL=${stop_loss:.2f} ({atr_pct*stop_mult*100:.1f}% away) "
            f"TP=${take_profit:.2f} ({atr_pct*tp_mult*100:.1f}% away) "
            f"R:R={rr:.2f}"
        )

        return bracket

    def build_from_signal(self, signal: dict, side: str = "long") -> Optional[Bracket]:
        """
        Build bracket directly from a screener signal dict.
        Handles missing atr_pct gracefully.
        """
        price   = float(signal.get("price", 0))
        atr_pct = float(signal.get("atr_pct", 0.015))
        ticker  = signal.get("ticker", "?")
        is_crypto = "/" in ticker

        if price <= 0:
            return None

        # Clamp ATR to reasonable range
        atr_pct = max(0.005, min(0.10, atr_pct))

        return self.build(
            ticker=ticker,
            entry=price,
            atr_pct=atr_pct,
            side=side,
            is_crypto=is_crypto,
        )

    def validate_bracket(self, bracket: Bracket, min_rr: float = 1.2) -> bool:
        """Return False if the bracket has degenerate R:R or crossed levels."""
        if bracket.rr_ratio < min_rr:
            logger.warning(
                f"Bracket rejected: R:R={bracket.rr_ratio:.2f} < {min_rr} minimum"
            )
            return False

        if bracket.side == "long":
            if bracket.stop_loss >= bracket.entry:
                logger.warning("Bracket rejected: stop_loss >= entry (long)")
                return False
            if bracket.take_profit <= bracket.entry:
                logger.warning("Bracket rejected: take_profit <= entry (long)")
                return False
        else:
            if bracket.stop_loss <= bracket.entry:
                logger.warning("Bracket rejected: stop_loss <= entry (short)")
                return False
            if bracket.take_profit >= bracket.entry:
                logger.warning("Bracket rejected: take_profit >= entry (short)")
                return False
            if bracket.take_profit <= 0:
                logger.warning(f"Bracket rejected: take_profit={bracket.take_profit:.2f} <= 0 (short)")
                return False

        return True
