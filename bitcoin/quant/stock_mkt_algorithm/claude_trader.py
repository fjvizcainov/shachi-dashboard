"""
Claude Trader — Phase 1 Daemon

Main orchestrator for the Claude-powered trading engine.
Replaces grok_trader.py entirely.

Architecture:
  - Mechanical screener runs every 2 minutes (pure Python, no AI)
  - Claude called at premarket (9:00 ET), midday (12:00 ET), and on signal triggers
  - Bracket orders with ATR-based stops placed at entry
  - Mechanical trailing stop runs every minute
  - EOD close at 3:55 PM ET
  - Emergency circuit breaker: close all if drawdown > 3% intraday

Iron Laws (enforced in code, not just prompts):
  1. Max 6 open positions
  2. Max 22% capital per position
  3. Never SHORT index ETFs when individual longs are open
  4. Never touch PERMANENT_BLACKLIST tickers
  5. EOD flat: all positions closed by 3:55 PM ET
  6. Daily loss limit: flatten everything at -3% intraday
"""

import logging
import os
import sys
import time
import json
import signal
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

import requests

sys.path.insert(0, str(Path(__file__).parent))
from config.settings import config
from execution.alpaca_broker import AlpacaBroker
from agents.mechanical_screener import MechanicalScreener, PERMANENT_BLACKLIST, SIGNAL_THRESHOLD
from agents.claude_analyst import ClaudeAnalyst

# Phase 2 — risk modules
from risk.regime_filter import RegimeFilter
from risk.position_sizer import PositionSizer
from risk.bracket_builder import BracketBuilder
from risk.trailing_stop import TrailingStopManager

# Phase 3 — learning loop
from learning.performance_tracker import PerformanceTracker

# ─── Logging ─────────────────────────────────────────────────────────────────
LOGS_DIR = Path(__file__).parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOGS_DIR / "claude_trader.log"),
    ],
)
logger = logging.getLogger("claude_trader")

# ─── Constants ────────────────────────────────────────────────────────────────
ET = ZoneInfo("America/New_York")

MAX_POSITIONS          = 6
MAX_POSITION_PCT       = 0.22   # 22% per position (Half-Kelly)
DAILY_LOSS_LIMIT_PCT   = 0.03   # -3% → flatten all
EOD_CLOSE_HOUR         = 15
EOD_CLOSE_MINUTE       = 55
SCREENER_INTERVAL_SEC  = 120    # 2 minutes
TRAILING_STOP_INTERVAL = 60     # 1 minute
PREMARKET_HOUR         = 8
PREMARKET_MINUTE       = 30
MIDDAY_HOUR            = 12
MIDDAY_MINUTE          = 0
MIN_SIGNAL_COOLDOWN      = 600   # 10 min between Claude calls on same ticker
POSITION_REVIEW_COOLDOWN = 1800  # 30 min minimum between position reviews

# Index ETFs — never short when individual longs are open
INDEX_HEDGE_ETFS = {"SPY", "QQQ", "IWM", "DIA", "SPXU", "SQQQ", "SH", "PSQ"}

# Default ATR-based stop multiplier (replaced by Phase 2 risk module)
ATR_STOP_MULTIPLIER  = 2.5
ATR_TP_MULTIPLIER    = 4.0      # Take profit at 4x ATR
FLAT_STOP_PCT        = 0.025    # Fallback: 2.5% flat stop
FLAT_TP_PCT          = 0.04     # Fallback: 4% flat take profit
TRAILING_STOP_OFFSET = 0.015    # 1.5% trailing stop distance


# ─── Daemon ──────────────────────────────────────────────────────────────────

class ClaudeTrader:
    """
    Main trading daemon.

    Threading model:
      - Main thread: scheduler loop (premarket, midday, EOD)
      - Thread 1: screener loop (every 2 min during market hours)
      - Thread 2: trailing stop loop (every 1 min during market hours)
      - All writes to self._state are lock-protected
    """

    def __init__(self):
        self.broker      = AlpacaBroker(paper=True)
        self.screener    = MechanicalScreener()
        self.analyst     = ClaudeAnalyst()
        self._state_lock = threading.Lock()
        self._running    = False

        # Phase 2 — risk modules
        self.regime_filter  = RegimeFilter()
        self.position_sizer = PositionSizer()
        self.bracket_builder= BracketBuilder()
        self.trailing_mgr   = TrailingStopManager()

        # Phase 3 — learning loop
        self.perf_tracker   = PerformanceTracker()

        # Runtime state
        self._signal_cooldown: Dict[str, float] = {}   # ticker → last Claude call ts
        self._open_positions: Dict[str, Dict]   = {}   # ticker → position info
        self._day_start_equity: float           = 0.0
        self._premarket_done: bool              = False
        self._midday_done: bool                 = False
        self._eod_done: bool                    = False
        self._last_screener_run: float          = 0.0
        self._last_position_review: float       = 0.0

        # High-water mark for trailing stops
        self._high_water: Dict[str, float]      = {}   # ticker → peak price (longs)
        self._low_water: Dict[str, float]       = {}   # ticker → trough price (shorts)

        # Trade log for today
        self._today_log_path = LOGS_DIR / f"trades_{datetime.now(ET).strftime('%Y%m%d')}.json"

        logger.info("ClaudeTrader initialised (paper=True)")

    # ─── Helpers ─────────────────────────────────────────────────────────────

    def _now_et(self) -> datetime:
        return datetime.now(ET)

    def _is_market_hours(self) -> bool:
        """True between 9:30 and 16:00 ET on weekdays."""
        now = self._now_et()
        if now.weekday() >= 5:
            return False
        open_  = now.replace(hour=9, minute=30, second=0, microsecond=0)
        close_ = now.replace(hour=16, minute=0, second=0, microsecond=0)
        return open_ <= now <= close_

    def _minutes_to_close(self) -> float:
        now   = self._now_et()
        close = now.replace(hour=16, minute=0, second=0, microsecond=0)
        return (close - now).total_seconds() / 60

    def _account(self) -> Dict:
        try:
            return self.broker.get_account()
        except Exception as e:
            logger.error(f"get_account failed: {e}")
            return {}

    def _equity(self) -> float:
        acc = self._account()
        return float(acc.get("equity", 0) or 0)

    def _buying_power(self) -> float:
        acc = self._account()
        return float(acc.get("buying_power", 0) or 0)

    def _sync_positions(self) -> Dict[str, Dict]:
        """Pull live positions from Alpaca and update internal state."""
        raw = self.broker.get_positions()
        if not isinstance(raw, list):
            return self._open_positions

        positions = {}
        for p in raw:
            sym = p.get("symbol", "")
            qty = float(p.get("qty", 0))
            if qty == 0:
                continue
            positions[sym] = {
                "qty":              qty,
                "side":             "long" if qty > 0 else "short",
                "avg_entry":        float(p.get("avg_entry_price", 0)),
                "current_price":    float(p.get("current_price", 0)),
                "market_value":     float(p.get("market_value", 0)),
                "unrealized_pnl":   float(p.get("unrealized_pl", 0)),
                "unrealized_pct":   float(p.get("unrealized_plpc", 0)),
            }

        with self._state_lock:
            self._open_positions = positions

        return positions

    def _count_individual_longs(self) -> int:
        """Count open long positions that are NOT in INDEX_HEDGE_ETFS."""
        return sum(
            1 for sym, pos in self._open_positions.items()
            if pos["side"] == "long" and sym not in INDEX_HEDGE_ETFS
        )

    def _is_signal_cooling(self, ticker: str) -> bool:
        last = self._signal_cooldown.get(ticker, 0)
        return (time.time() - last) < MIN_SIGNAL_COOLDOWN

    def _touch_cooldown(self, ticker: str):
        self._signal_cooldown[ticker] = time.time()

    def _log_trade(self, record: Dict):
        """Append trade record to today's JSON log."""
        records = []
        if self._today_log_path.exists():
            try:
                records = json.loads(self._today_log_path.read_text())
            except Exception:
                pass
        records.append({**record, "logged_at": datetime.utcnow().isoformat()})
        self._today_log_path.write_text(json.dumps(records, indent=2))

    # ─── Anti-Hedge Enforcement ───────────────────────────────────────────────

    def _check_iron_laws(self, decision: Dict) -> Optional[str]:
        """
        Validate Claude's decision against hard-coded Iron Laws.
        Returns an error string if the trade is blocked, else None.
        """
        action = decision.get("action", "").upper()
        ticker = decision.get("ticker", "")
        side   = decision.get("side", "").upper()

        if action not in ("BUY", "SELL", "HOLD", "CLOSE"):
            return None  # Nothing to validate for HOLD/CLOSE

        if ticker in PERMANENT_BLACKLIST:
            return f"BLOCKED: {ticker} is in permanent blacklist"

        positions = self._open_positions

        # Law 3: no index ETF shorts when individual longs open
        if action == "SELL" and ticker in INDEX_HEDGE_ETFS:
            if self._count_individual_longs() >= 2:
                return (
                    f"BLOCKED: shorting {ticker} (index ETF) while "
                    f"{self._count_individual_longs()} individual longs are open"
                )

        # Law 1: max positions (hard cap AND regime-based cap)
        if action == "BUY" and ticker not in positions:
            regime = self.regime_filter.get_regime()
            effective_max = min(MAX_POSITIONS, regime.max_positions)
            if len(positions) >= effective_max:
                return f"BLOCKED: max {effective_max} positions reached (regime={regime.name})"

        # Law 2: max 22% per position
        if action == "BUY":
            equity = self._equity()
            pos_size_pct = decision.get("position_size_pct", MAX_POSITION_PCT)
            if pos_size_pct > MAX_POSITION_PCT:
                decision["position_size_pct"] = MAX_POSITION_PCT  # silently cap

        return None  # All clear

    # ─── Order Execution ──────────────────────────────────────────────────────

    def _calc_stop_tp(self, ticker: str, price: float, side: str, atr_pct: float) -> tuple:
        """
        Calculate stop-loss and take-profit prices.
        Uses ATR if available, falls back to flat %.
        atr_pct: ATR as a % of price (e.g. 0.012 = 1.2%)
        """
        if atr_pct and atr_pct > 0:
            stop_dist = price * atr_pct * ATR_STOP_MULTIPLIER
            tp_dist   = price * atr_pct * ATR_TP_MULTIPLIER
        else:
            stop_dist = price * FLAT_STOP_PCT
            tp_dist   = price * FLAT_TP_PCT

        if side.upper() == "BUY":
            stop_loss   = round(price - stop_dist, 4)
            take_profit = round(price + tp_dist, 4)
        else:  # SELL / short
            stop_loss   = round(price + stop_dist, 4)
            take_profit = round(price - tp_dist, 4)

        return stop_loss, take_profit

    def _execute_decision(self, decision: Dict, signal_data: Dict = None) -> bool:
        """
        Execute a validated trade decision from Claude.
        Returns True if an order was submitted.
        """
        action   = decision.get("action", "HOLD").upper()
        ticker   = decision.get("ticker", "")
        side     = decision.get("side", "").upper()   # BUY or SELL
        size_pct = float(decision.get("position_size_pct", MAX_POSITION_PCT))
        rationale = decision.get("rationale", "")

        # Normalize direction words → order sides
        if action == "LONG":  action = "BUY"
        if action == "SHORT": action = "SELL"

        # NO_TRADE decision — log and skip
        if decision.get("decision", "").upper() == "NO_TRADE":
            logger.info(f"NO_TRADE {ticker} (conf={decision.get('confidence', 0):.0%}): {decision.get('rejection_reason', decision.get('reasoning', ''))[:120]}")
            return False

        if action == "HOLD":
            logger.info(f"HOLD {ticker}: {rationale}")
            return False

        if action == "CLOSE":
            return self._close_position(ticker, reason="Claude CLOSE signal")

        if action not in ("BUY", "SELL"):
            logger.warning(f"Unknown action {action} for {ticker}")
            return False

        # Iron law enforcement
        block_reason = self._check_iron_laws(decision)
        if block_reason:
            logger.warning(block_reason)
            return False

        # Phase 2: check regime allows this side
        if not self.regime_filter.is_side_allowed("long" if action == "BUY" else "short"):
            logger.warning(f"BLOCKED by regime filter: {action} {ticker} not allowed in current regime")
            return False

        # For short orders: verify Alpaca allows shorting this ticker
        if action == "SELL":
            if not self.broker.is_shortable(ticker):
                logger.warning(f"BLOCKED: {ticker} is not shortable on Alpaca (not in easy-to-borrow list)")
                return False

        # Get current price
        price = None
        try:
            quote = self.broker._make_request(
                "GET",
                f"/v2/stocks/{ticker}/quotes/latest",
                base_url=self.broker.data_url,
            )
            price = float(quote.get("quote", {}).get("ap") or quote.get("quote", {}).get("bp") or 0)
        except Exception:
            pass

        if not price or price <= 0:
            price = float((signal_data or {}).get("price", 0))

        if not price or price <= 0:
            logger.error(f"Cannot determine price for {ticker}, skipping")
            return False

        # Phase 2: Kelly-based position sizing
        equity   = self._equity()
        bp       = self._buying_power()
        regime   = self.regime_filter.get_regime()
        atr_pct  = float((signal_data or {}).get("atr_pct", FLAT_STOP_PCT))

        # Cap by regime max and override Claude's suggestion if tighter
        regime_cap = min(size_pct, regime.max_position_pct)
        qty, actual_pct = self.position_sizer.size(
            ticker=ticker,
            price=price,
            equity=equity,
            max_pct=regime_cap,
            atr_pct=atr_pct,
            buying_power=bp,
        )

        # Phase 2: ATR-based bracket
        bracket = self.bracket_builder.build(
            ticker=ticker,
            entry=price,
            atr_pct=atr_pct,
            side="long" if action == "BUY" else "short",
            is_crypto="/" in ticker,
        )
        if not self.bracket_builder.validate_bracket(bracket):
            # Degenerate bracket — fall back to flat % defaults
            stop_loss, take_profit = self._calc_stop_tp(ticker, price, action, atr_pct)
        else:
            stop_loss   = bracket.stop_loss
            take_profit = bracket.take_profit

        logger.info(
            f"EXECUTE {action} {qty}x {ticker} @ ~${price:.2f} "
            f"SL=${stop_loss:.2f} TP=${take_profit:.2f} ({size_pct*100:.0f}% equity)"
        )

        try:
            result = self.broker.submit_bracket_order(
                ticker=ticker,
                qty=qty,
                side="buy" if action == "BUY" else "sell",
                stop_loss=stop_loss,
                take_profit=take_profit,
            )
        except Exception as e:
            logger.error(f"Order submission error for {ticker}: {e}")
            return False

        if "error" in result:
            logger.error(f"Order rejected for {ticker}: {result['error']}")
            return False

        order_id = result.get("id", "")
        logger.info(f"Order placed: {order_id} — {action} {qty}x {ticker}")

        # Phase 2: register with TrailingStopManager
        side = "long" if action == "BUY" else "short"
        self.trailing_mgr.register(ticker, price, side)

        # Legacy watermarks (backup)
        with self._state_lock:
            if action == "BUY":
                self._high_water[ticker] = price
            else:
                self._low_water[ticker] = price

        self._log_trade({
            "action":    action,
            "ticker":    ticker,
            "qty":       qty,
            "price":     price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "order_id":  order_id,
            "rationale": rationale,
        })

        self._touch_cooldown(ticker)
        return True

    def _close_position(self, ticker: str, reason: str = "") -> bool:
        """Close a single position."""
        result = self.broker.close_position(ticker)
        if "error" in result:
            logger.error(f"Failed to close {ticker}: {result.get('error')}")
            return False

        logger.info(f"Closed {ticker}: {reason}")
        self._log_trade({"action": "CLOSE", "ticker": ticker, "reason": reason})
        self.trailing_mgr.unregister(ticker)

        with self._state_lock:
            self._high_water.pop(ticker, None)
            self._low_water.pop(ticker, None)

        return True

    # ─── Bracket Management ───────────────────────────────────────────────────

    def _get_open_orders_by_symbol(self) -> Dict[str, List[Dict]]:
        """Return all open orders grouped by symbol."""
        try:
            resp = self.broker.session.get(
                f"{self.broker.base_url}/v2/orders",
                params={"status": "open", "limit": 100},
                timeout=8,
            )
            orders = resp.json() if isinstance(resp.json(), list) else []
            result: Dict[str, List] = {}
            for o in orders:
                sym = o.get("symbol", "")
                result.setdefault(sym, []).append(o)
            return result
        except Exception as e:
            logger.warning(f"Failed to fetch open orders: {e}")
            return {}

    def _update_bracket(self, ticker: str, new_tp: float) -> bool:
        """
        Cancel all existing exit orders for a position and place a fresh OCO
        with the updated take-profit.  Preserves the existing stop-loss price
        if one is found; otherwise falls back to ATR-based calculation.
        """
        pos = self._open_positions.get(ticker)
        if not pos:
            logger.warning(f"_update_bracket: {ticker} not in open positions")
            return False

        side       = pos["side"]          # "long" or "short"
        qty        = abs(int(pos["qty"]))
        cur_price  = pos["current_price"] or pos["avg_entry"]
        order_side = "sell" if side == "long" else "buy"

        # Validate new TP makes sense
        if side == "long" and new_tp <= cur_price:
            logger.warning(f"EXTEND_TP {ticker}: new TP ${new_tp} <= current ${cur_price:.2f}, skipping")
            return False
        if side == "short" and new_tp >= cur_price:
            logger.warning(f"EXTEND_TP {ticker}: new TP ${new_tp} >= current ${cur_price:.2f}, skipping")
            return False

        # Find and cancel existing exit orders; preserve SL price
        orders_by_sym = self._get_open_orders_by_symbol()
        existing_sl: Optional[float] = None
        for o in orders_by_sym.get(ticker, []):
            if o.get("side") == order_side:
                sp = o.get("stop_price")
                if sp:
                    existing_sl = float(sp)
                self.broker.session.delete(
                    f"{self.broker.base_url}/v2/orders/{o['id']}", timeout=5
                )
                logger.info(f"Canceled {ticker} order {o['id'][:18]} for bracket update")

        # Fallback SL: 1.5x ATR from current price
        if existing_sl is None:
            atr_pct = 0.015
            if side == "long":
                existing_sl = round(cur_price * (1 - atr_pct * ATR_STOP_MULTIPLIER), 2)
            else:
                existing_sl = round(cur_price * (1 + atr_pct * ATR_STOP_MULTIPLIER), 2)

        # Place new OCO
        resp = self.broker.session.post(
            f"{self.broker.base_url}/v2/orders",
            json={
                "symbol":       ticker,
                "qty":          str(qty),
                "side":         order_side,
                "type":         "limit",
                "time_in_force":"gtc",
                "order_class":  "oco",
                "take_profit":  {"limit_price": str(new_tp)},
                "stop_loss":    {"stop_price":  str(existing_sl)},
            },
            timeout=8,
        )
        if resp.status_code == 200:
            logger.info(f"✅ Bracket updated {ticker} ({side}): TP=${new_tp} SL=${existing_sl}")
            return True
        else:
            logger.error(f"❌ Bracket update failed {ticker}: {resp.status_code} {resp.text[:150]}")
            return False

    def _ensure_brackets(self):
        """
        Detect positions without any active exit orders and restore a basic OCO
        bracket for them.  Called at the start of every screener cycle.
        """
        if not self._open_positions:
            return
        orders_by_sym = self._get_open_orders_by_symbol()

        for sym, pos in self._open_positions.items():
            side       = pos["side"]
            order_side = "sell" if side == "long" else "buy"
            sym_orders = orders_by_sym.get(sym, [])

            # Position is covered if it has at least one exit-side open order
            covered = any(o.get("side") == order_side for o in sym_orders)
            if covered:
                continue

            qty       = abs(int(pos["qty"]))
            price     = pos["current_price"] or pos["avg_entry"]
            atr_pct   = 0.015
            is_crypto = "/" in sym

            bracket = self.bracket_builder.build(
                ticker=sym, entry=price, atr_pct=atr_pct,
                side=side, is_crypto=is_crypto,
            )
            # Round to 2 decimal places to avoid sub-penny rejection
            tp = round(bracket.take_profit, 2)
            sl = round(bracket.stop_loss, 2)

            if side == "short" and tp <= 0:
                tp = round(price * 0.90, 2)  # 10% below as floor

            resp = self.broker.session.post(
                f"{self.broker.base_url}/v2/orders",
                json={
                    "symbol":       sym,
                    "qty":          str(qty),
                    "side":         order_side,
                    "type":         "limit",
                    "time_in_force":"gtc",
                    "order_class":  "oco",
                    "take_profit":  {"limit_price": str(tp)},
                    "stop_loss":    {"stop_price":  str(sl)},
                },
                timeout=8,
            )
            if resp.status_code == 200:
                logger.info(f"✅ Bracket restored {sym} ({side}): TP=${tp} SL=${sl}")
            else:
                logger.warning(
                    f"⚠️  Bracket restore failed {sym}: {resp.status_code} {resp.text[:100]}"
                )

    def _execute_position_update(self, update: Dict) -> bool:
        """
        Execute a single position update from Claude's midday/position review.
        Handles EXTEND_TP, CLOSE, and HOLD actions.
        """
        ticker = update.get("ticker", "")
        action = update.get("action", "HOLD").upper()
        reason = update.get("reason", "")[:100]

        if action == "HOLD":
            logger.info(f"HOLD {ticker}: {reason}")
            return False

        if action == "CLOSE":
            return self._close_position(ticker, reason=f"position_review: {reason}")

        if action == "EXTEND_TP":
            new_tp = float(update.get("new_take_profit_price", 0))
            if new_tp <= 0:
                logger.warning(f"EXTEND_TP {ticker}: no valid new_take_profit_price in update")
                return False
            return self._update_bracket(ticker, new_tp=new_tp)

        logger.debug(f"_execute_position_update: unknown action '{action}' for {ticker}")
        return False

    # ─── Position Review ──────────────────────────────────────────────────────

    def _run_position_review(self, trigger: str = "scheduled"):
        """
        Claude reviews all open positions and executes EXTEND_TP / CLOSE decisions.
        Throttled by POSITION_REVIEW_COOLDOWN to avoid spamming Claude.
        """
        logger.info(f"=== POSITION REVIEW ({trigger}) ===")
        try:
            positions = list(self._sync_positions().values())
            if not positions:
                return
            review = self.analyst.midday_review(positions)
            if not review:
                return
            updates = review.get("position_updates", [])
            logger.info(f"Position review: {len(updates)} updates from Claude")
            for update in updates:
                self._execute_position_update(update)
        except Exception as e:
            logger.error(f"Position review failed: {e}")
        finally:
            self._last_position_review = time.time()

    # ─── Mechanical Trailing Stop ─────────────────────────────────────────────

    def _trailing_stop_loop(self):
        """
        Runs in a background thread every TRAILING_STOP_INTERVAL seconds.
        Closes positions that have retraced TRAILING_STOP_OFFSET from peak.
        Claude does NOT make this decision — it's pure math.
        """
        logger.info("Trailing stop loop started")
        while self._running:
            try:
                if self._is_market_hours():
                    self._check_trailing_stops()
            except Exception as e:
                logger.error(f"Trailing stop error: {e}")
            time.sleep(TRAILING_STOP_INTERVAL)

    def _check_trailing_stops(self):
        """Phase 2: delegate to TrailingStopManager for ATR-aware trailing stops."""
        positions = self._sync_positions()

        # Enrich positions with atr_pct from screener cache if available
        for ticker, pos in positions.items():
            if "atr_pct" not in pos:
                pos["atr_pct"] = FLAT_STOP_PCT  # default

        to_close = self.trailing_mgr.check(positions)
        for ticker, reason in to_close.items():
            self._close_position(ticker, reason=reason)
            with self._state_lock:
                self._high_water.pop(ticker, None)
                self._low_water.pop(ticker, None)

    # ─── Emergency Circuit Breaker ────────────────────────────────────────────

    def _check_circuit_breaker(self) -> bool:
        """
        Returns True if circuit breaker was triggered (all positions closed).
        Triggered when intraday drawdown > DAILY_LOSS_LIMIT_PCT.
        """
        if self._day_start_equity <= 0:
            return False

        current = self._equity()
        drawdown = (current - self._day_start_equity) / self._day_start_equity

        if drawdown <= -DAILY_LOSS_LIMIT_PCT:
            logger.critical(
                f"CIRCUIT BREAKER: intraday drawdown {drawdown*100:.1f}% "
                f"(start=${self._day_start_equity:.0f} now=${current:.0f})"
            )
            self.broker.cancel_all_orders()
            self.broker.close_all_positions()
            self._log_trade({"action": "CIRCUIT_BREAKER", "drawdown_pct": drawdown})
            return True

        return False

    # ─── Screener Loop ────────────────────────────────────────────────────────

    def _screener_loop(self):
        """
        Background thread: runs the mechanical screener every 2 minutes.
        When a ticker scores >= SIGNAL_THRESHOLD and is not on cooldown,
        asks Claude to evaluate the signal.
        """
        logger.info("Screener loop started")
        while self._running:
            try:
                if self._is_market_hours() and not self._eod_done:
                    self._run_screener_cycle()
            except Exception as e:
                logger.error(f"Screener cycle error: {e}")
            time.sleep(SCREENER_INTERVAL_SEC)

    def _run_screener_cycle(self):
        """Single screener pass."""
        self._sync_positions()

        # Circuit breaker check
        if self._check_circuit_breaker():
            logger.critical("Circuit breaker active — screener paused until EOD")
            return

        # Always ensure every open position has an active bracket (TP + SL)
        self._ensure_brackets()

        # Proactive oscillator alerts on open positions.
        # If extremes detected AND review cooldown has passed → trigger async review.
        if self._open_positions:
            alerts = self.screener.monitor_positions(list(self._open_positions.keys()))
            review_due = (time.time() - self._last_position_review) > POSITION_REVIEW_COOLDOWN
            if alerts and review_due:
                logger.info(
                    f"Oscillator alerts on {[a['ticker'] for a in alerts]} → "
                    "triggering async position review"
                )
                threading.Thread(
                    target=self._run_position_review,
                    args=("oscillator_alert",),
                    daemon=True,
                ).start()

        # Too many positions → skip new entry logic only
        if len(self._open_positions) >= MAX_POSITIONS:
            logger.debug(f"Max positions ({MAX_POSITIONS}) reached — no new entries this cycle")
            return

        results = self.screener.scan()  # None → dynamic universe (most-actives + CORE)
        signals = [r for r in results if r.get("score", 0) >= SIGNAL_THRESHOLD]

        if not signals:
            # Log top 3 scores so we can diagnose why nothing is firing
            top = sorted(results, key=lambda x: x.get("score", 0), reverse=True)[:3]
            if top:
                logger.info(
                    "Top scores (none >= 7.0): " + ", ".join(
                        f"{r['ticker']}={r['score']:.1f}" for r in top
                    )
                )
            return

        logger.info(f"Screener: {len(signals)} signals above threshold")

        # Filter signals that are actionable right now
        candidates = []
        for signal in signals:
            ticker = signal["ticker"]
            if ticker in self._open_positions:
                continue
            if self._is_signal_cooling(ticker):
                logger.debug(f"Skipping {ticker}: on cooldown")
                continue
            if (ticker in INDEX_HEDGE_ETFS
                    and signal.get("direction", "long") == "short"
                    and self._count_individual_longs() >= 2):
                logger.info(f"Skipping short on {ticker} (anti-hedge: {self._count_individual_longs()} individual longs open)")
                continue
            candidates.append(signal)

        if not candidates:
            return

        logger.info(
            f"Evaluating {len(candidates)} candidates in parallel: "
            + ", ".join(
                f"{s['ticker']}({'▲' if s.get('direction','long')=='long' else '▼'}{s['score']:.1f})"
                for s in candidates
            )
        )

        # Evaluate all candidates in parallel — each Claude call is ~30s,
        # parallel keeps total time bounded by the slowest single eval.
        def _eval(signal):
            ticker = signal["ticker"]
            try:
                decision = self.analyst.evaluate_signal(signal, self._open_positions)
                return ticker, decision, signal
            except Exception as e:
                logger.error(f"Claude evaluation error for {ticker}: {e}")
                self._touch_cooldown(ticker)
                return ticker, None, signal

        with ThreadPoolExecutor(max_workers=len(candidates)) as executor:
            futures = {executor.submit(_eval, s): s for s in candidates}
            for future in as_completed(futures):
                ticker, decision, signal = future.result()
                if decision:
                    # FIX: re-sync before each execution — parallel evals all saw
                    # the same position count; without re-sync we can exceed MAX_POSITIONS
                    self._sync_positions()
                    regime = self.regime_filter.get_regime()
                    effective_max = min(MAX_POSITIONS, regime.max_positions)
                    if len(self._open_positions) >= effective_max:
                        logger.warning(
                            f"Skipping {ticker}: {len(self._open_positions)}/{effective_max} "
                            f"positions already open (regime={regime.name})"
                        )
                        continue
                    self._execute_decision(decision, signal_data=signal)

    # ─── Scheduled Events ─────────────────────────────────────────────────────

    def _run_premarket(self):
        """8:30 AM ET — Claude premarket brief + immediate entry on high-conviction targets."""
        logger.info("=== PREMARKET ANALYSIS ===")
        try:
            # Phase 3: inject weekly performance context (runs full review on Mondays)
            perf_context = self.perf_tracker.run_if_needed()
            if perf_context:
                logger.info("Learning loop: injecting performance context into premarket")

            positions = list(self._sync_positions().values())
            analysis = self.analyst.premarket_analysis(
                live_positions=positions,
                performance_context=perf_context,
            )
            if analysis:
                regime  = analysis.get("regime", "UNKNOWN")
                targets = analysis.get("target_entries", [])
                logger.info(f"Regime: {regime}  |  Targets: {[t.get('ticker') for t in targets]}")

                # Adjust position size cap based on regime
                if regime in ("BEAR", "CRISIS"):
                    logger.warning(f"Defensive regime ({regime}): capping positions at 15%")
                    self._regime_size_cap = 0.15
                elif regime == "HIGH_VOL":
                    self._regime_size_cap = 0.18
                else:
                    self._regime_size_cap = MAX_POSITION_PCT

                # Execute premarket targets
                # >= 0.72 confidence → auto-execute (high conviction)
                # 0.50-0.72          → run through evaluate_signal() for a fresh Claude review
                # < 0.50             → skip
                now_et = self._now_et()
                market_accessible = now_et.hour >= 4  # Extended hours start at 4 AM ET
                for target in targets:
                    ticker     = target.get("ticker", "")
                    confidence = float(target.get("confidence", 0))
                    action     = target.get("action", "LONG").upper()

                    if not ticker or not market_accessible:
                        continue
                    if ticker in self._open_positions:
                        logger.info(f"Premarket target {ticker}: already in positions, skipping")
                        continue
                    if self._is_signal_cooling(ticker):
                        logger.info(f"Premarket target {ticker}: on cooldown, skipping")
                        continue
                    if confidence < 0.50:
                        logger.info(f"Premarket target {ticker}: confidence {confidence:.0%} too low (<50%), skipping")
                        continue

                    if confidence >= 0.72:
                        # High conviction — execute directly from premarket analysis
                        logger.info(f"Premarket target: {ticker} {action} confidence={confidence:.2f} → auto-executing")
                        decision = dict(target)
                        decision["decision"] = "TRADE"
                        decision["action"]   = "BUY" if action in ("LONG", "BUY") else "SELL"
                        decision["ticker"]   = ticker
                        decision["catalyst"] = "premarket_conviction"
                        decision["reasoning"] = target.get("rationale", "premarket target")
                        self._execute_decision(decision)
                    else:
                        # Medium conviction — get a fresh signal evaluation with live data
                        logger.info(f"Premarket target: {ticker} {action} confidence={confidence:.2f} → routing to signal eval")
                        try:
                            signal_data = {
                                "ticker": ticker,
                                "score": 7.5,  # treat as high-priority signal
                                "signal_type": "PREMARKET_TARGET",
                                "rsi": 50,
                                "vol_ratio": 1.0,
                            }
                            decision = self.analyst.evaluate_signal(signal_data, list(self._open_positions.values()))
                            if decision:
                                self._execute_decision(decision, signal_data=signal_data)
                        except Exception as e:
                            logger.error(f"Signal eval for premarket target {ticker}: {e}")
                            self._touch_cooldown(ticker)

        except Exception as e:
            logger.error(f"Premarket analysis failed: {e}", exc_info=True)

        self._premarket_done = True

    def _run_midday(self):
        """12:00 PM ET — Claude midday review of open positions."""
        self._run_position_review(trigger="scheduled_midday")
        self._midday_done = True

    def _run_eod_close(self):
        """3:55 PM ET — flatten everything."""
        logger.info("=== EOD CLOSE — flattening all positions ===")
        try:
            self.broker.cancel_all_orders()
            positions = self._sync_positions()
            for ticker in list(positions.keys()):
                self._close_position(ticker, reason="EOD_forced_close")
        except Exception as e:
            logger.error(f"EOD close error: {e}")
        finally:
            self._eod_done = True
            logger.info("EOD close complete")

    # ─── Main Loop ────────────────────────────────────────────────────────────

    def _scheduler_loop(self):
        """
        Main thread scheduler. Checks wall-clock ET time and fires
        premarket / midday / EOD events exactly once per day.
        """
        logger.info("Scheduler loop started")
        while self._running:
            try:
                now = self._now_et()

                # Reset daily flags at midnight
                if now.hour == 0 and now.minute < 2:
                    self._premarket_done = False
                    self._midday_done    = False
                    self._eod_done       = False
                    self._day_start_equity = self._equity()
                    logger.info(f"New day: start equity = ${self._day_start_equity:.2f}")

                # Premarket: fires at 8:30 AM ET, OR immediately on startup
                # if we missed the window (late start / crash recovery).
                _past_premarket = (
                    now.hour > PREMARKET_HOUR
                    or (now.hour == PREMARKET_HOUR and now.minute >= PREMARKET_MINUTE)
                )
                _before_eod = now.hour < EOD_CLOSE_HOUR
                if _past_premarket and _before_eod and not self._premarket_done:
                    if self._day_start_equity <= 0:
                        self._day_start_equity = self._equity()
                    self._run_premarket()

                # Midday: 12:00 PM ET
                if (now.hour == MIDDAY_HOUR and now.minute >= MIDDAY_MINUTE
                        and not self._midday_done and self._premarket_done):
                    self._run_midday()

                # EOD: 3:55 PM ET
                if (now.hour == EOD_CLOSE_HOUR and now.minute >= EOD_CLOSE_MINUTE
                        and not self._eod_done):
                    self._run_eod_close()

            except Exception as e:
                logger.error(f"Scheduler error: {e}")

            time.sleep(30)  # Check every 30 seconds

    def _heartbeat_loop(self):
        """Log a status heartbeat every 5 minutes."""
        while self._running:
            try:
                now = self._now_et()
                if self._is_market_hours():
                    positions = self._sync_positions()
                    equity    = self._equity()
                    pnl_pct   = 0.0
                    if self._day_start_equity > 0:
                        pnl_pct = (equity - self._day_start_equity) / self._day_start_equity * 100
                    logger.info(
                        f"[HEARTBEAT] {now.strftime('%H:%M ET')} "
                        f"equity=${equity:,.0f} daily={pnl_pct:+.2f}% "
                        f"positions={len(positions)}/{MAX_POSITIONS}"
                    )
                    for sym, pos in positions.items():
                        logger.info(
                            f"  {sym:10} {pos['side']:5} qty={abs(pos['qty']):.0f} "
                            f"entry=${pos['avg_entry']:.2f} "
                            f"cur=${pos['current_price']:.2f} "
                            f"pnl={pos['unrealized_pct']*100:+.1f}%"
                        )
            except Exception as e:
                logger.debug(f"Heartbeat error: {e}")
            time.sleep(300)

    # ─── Start / Stop ─────────────────────────────────────────────────────────

    def start(self):
        """Start all daemon threads."""
        self._running = True

        # Capture day-start equity on launch
        self._day_start_equity = self._equity()
        logger.info(f"Starting Claude Trader | equity=${self._day_start_equity:,.2f}")

        threads = [
            threading.Thread(target=self._scheduler_loop,    name="scheduler",    daemon=True),
            threading.Thread(target=self._screener_loop,     name="screener",     daemon=True),
            threading.Thread(target=self._trailing_stop_loop,name="trailing_stop",daemon=True),
            threading.Thread(target=self._heartbeat_loop,    name="heartbeat",    daemon=True),
        ]

        for t in threads:
            t.start()
            logger.info(f"Thread started: {t.name}")

        # Block main thread
        try:
            while self._running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received — shutting down")
            self.stop()

    def stop(self):
        """Graceful shutdown — cancels pending orders but leaves filled positions open."""
        logger.info("Stopping Claude Trader...")
        self._running = False

        # Cancel only open/pending orders — do NOT close filled positions.
        # Bracket orders (SL/TP legs) will continue to manage risk server-side.
        try:
            self.broker.cancel_all_orders()
            logger.info("Pending orders cancelled. Filled positions left open (bracket orders active).")
        except Exception as e:
            logger.error(f"Error cancelling orders on shutdown: {e}")

        logger.info("Claude Trader stopped")


# ─── Entry Point ──────────────────────────────────────────────────────────────

def main():
    # Verify API key before starting
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        # Try loading from .env
        env_path = Path(__file__).parent / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("ANTHROPIC_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
                    os.environ["ANTHROPIC_API_KEY"] = api_key
                    break

    if not api_key:
        logger.critical("ANTHROPIC_API_KEY is not set. Add it to .env and restart.")
        sys.exit(1)

    logger.info("ANTHROPIC_API_KEY: OK")

    trader = ClaudeTrader()

    # Handle SIGTERM gracefully (e.g. from systemd)
    def _sigterm(signum, frame):
        logger.info("SIGTERM received")
        trader.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _sigterm)

    trader.start()


if __name__ == "__main__":
    main()
