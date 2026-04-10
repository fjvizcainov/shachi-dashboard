"""
Stock Market Algorithm - Dashboard Server

Real-time monitoring dashboard with:
- Portfolio status
- Live positions
- Trade history
- Performance metrics
- Technical indicators
"""

from flask import Flask, jsonify, render_template, send_from_directory, request
from flask_cors import CORS
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import logging
import json
import os
import sys

# Add parent to path (stock_mkt_algorithm dir) - MUST be first for correct imports
_parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Add quant root for V5 (add after parent so parent takes precedence)
_quant_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Insert quant root first, then parent - so parent ends up at index 0
if _quant_root not in sys.path:
    sys.path.insert(0, _quant_root)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)  # This will be at index 0, searched first

from config.settings import config
from data_sources.polygon_client import PolygonClient
from features.technical import TechnicalFeatures
from execution.alpaca_broker import AlpacaBroker

app = Flask(__name__, static_folder='.', template_folder='.')
CORS(app)

# Initialize Alpaca broker for live positions
alpaca_broker = AlpacaBroker()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize data client
data_client = PolygonClient()
features_calc = TechnicalFeatures()

# In-memory state (would be Redis in production)
state = {
    'positions': [],
    'trades': [],
    'equity_curve': [100000],
    'initial_capital': 100000,
    'last_update': None,
}


@app.route('/')
def index():
    """Serve dashboard HTML."""
    return send_from_directory('.', 'index.html')


@app.route('/v5')
def index_v5():
    """Serve V5 dashboard HTML."""
    return send_from_directory('.', 'index_v5.html')


@app.route('/api/v5/dashboard')
def get_v5_dashboard():
    """Get V5 dashboard data."""
    try:
        from generate_data_v5 import generate_dashboard_data

        offset = request.args.get('offset', 0, type=int)
        limit = request.args.get('limit', 30, type=int)

        data = generate_dashboard_data(trades_limit=limit, trades_offset=offset)
        return jsonify(data)
    except ImportError as e:
        logger.warning(f"V5 data generator not available: {e}")
        # Return mock data structure
        return jsonify({
            'timestamp': datetime.now().isoformat(),
            'version': '5.0.0',
            'system_status': {
                'trading_enabled': False,
                'breaker_triggered': False,
                'model_version': 'not_loaded',
                'n_features': 12,
                'regime': 'unknown',
            },
            'current_position': None,
            'equity': {
                'current': 10000.0,
                'peak': 10000.0,
                'initial': 10000.0,
                'drawdown_pct': 0.0,
                'daily_pnl': 0.0,
            },
            'oos_metrics': {
                'total_trades': 0,
                'direction_accuracy': 0,
                'win_rate': 0,
                'profit_factor': 0,
                'total_pnl_pct': 0,
                'max_drawdown_pct': 0,
                'avg_monthly_return': 0,
            },
            'exit_breakdown': {
                'trailing_stop': 0,
                'stop_loss': 0,
                'time_stop': 0,
                'regime_change': 0,
            },
            'trades': [],
            'total_trades': 0,
            'trades_offset': 0,
            'trades_limit': 30,
            'config': {
                'leverage': 1.0,
                'position_sizes': {'low': 0.10, 'medium': 0.15, 'high': 0.20},
                'long_threshold': 1.2,
                'short_threshold': -1.5,
                'sl_atr_multiplier': 3.5,
                'trailing_activation_pct': 1.5,
                'trailing_atr_multiplier': 1.5,
            },
            'realistic_ranges': {
                'direction_accuracy': [51, 55],
                'win_rate': [45, 55],
                'profit_factor': [1.1, 1.3],
                'monthly_return': [0.5, 2.0],
                'max_drawdown': [15, 25],
            },
        })
    except Exception as e:
        logger.error(f"V5 dashboard error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/status')
def get_status():
    """Get system status."""
    return jsonify({
        'status': 'running',
        'mode': 'paper' if config.paper_trading else 'live',
        'last_update': state['last_update'],
        'uptime_hours': 24,  # Would calculate from start time
    })


@app.route('/api/portfolio')
def get_portfolio():
    """Get portfolio summary using real Alpaca equity."""
    INITIAL_CAPITAL = 100_000.0
    try:
        account = alpaca_broker.get_account()
        current = round(float(account.get('equity', 0)), 2)
        last_equity = round(float(account.get('last_equity', current)), 2)
    except Exception:
        current = state['equity_curve'][-1] if state['equity_curve'] else INITIAL_CAPITAL
        last_equity = current

    initial = INITIAL_CAPITAL
    total_return = (current / initial - 1) * 100
    daily_return = (current / last_equity - 1) * 100 if last_equity else 0

    # Max drawdown from weekly equity curve (if available)
    equity = state['equity_curve']
    if len(equity) > 1:
        peak = np.maximum.accumulate(equity)
        drawdown = (np.array(equity) - peak) / peak
        max_dd = drawdown.min() * 100
    else:
        max_dd = 0

    return jsonify({
        'initial_capital': initial,
        'current_equity': current,
        'total_return_pct': round(total_return, 2),
        'daily_return_pct': round(daily_return, 2),
        'max_drawdown_pct': round(max_dd, 2),
        'n_positions': len(state['positions']),
        'n_trades': len(state['trades']),
    })


@app.route('/api/positions')
def get_positions():
    """Get current positions from Alpaca (real-time)."""
    try:
        positions = alpaca_broker.get_positions()

        result = []
        for pos in positions:
            symbol = pos.get('symbol', '')
            qty = int(pos.get('qty', 0))
            entry_price = float(pos.get('avg_entry_price', 0))
            current_price = float(pos.get('current_price', entry_price))
            market_value = float(pos.get('market_value', 0))
            unrealized_pl = float(pos.get('unrealized_pl', 0))
            unrealized_plpc = float(pos.get('unrealized_plpc', 0)) * 100

            result.append({
                'symbol': symbol,
                'side': 'LONG' if qty > 0 else 'SHORT',
                'qty': abs(qty),
                'entry_price': round(entry_price, 2),
                'current_price': round(current_price, 2),
                'market_value': round(market_value, 2),
                'unrealized_pnl': round(unrealized_pl, 2),
                'unrealized_pnl_pct': round(unrealized_plpc, 2),
                'timestamp': datetime.now().isoformat(),
            })

        return jsonify(result)
    except Exception as e:
        logger.error(f"Error fetching positions: {e}")
        return jsonify([])


@app.route('/api/orders')
def get_orders():
    """Get pending and recent orders from Alpaca."""
    try:
        # Get open orders
        open_orders = alpaca_broker.get_orders(status='open', limit=20)

        result = []
        for order in open_orders:
            result.append({
                'id': order.get('id', ''),
                'symbol': order.get('symbol', ''),
                'side': order.get('side', '').upper(),
                'qty': order.get('qty', 0),
                'type': order.get('type', ''),
                'limit_price': order.get('limit_price'),
                'status': order.get('status', ''),
                'created_at': order.get('created_at', ''),
            })

        return jsonify(result)
    except Exception as e:
        logger.error(f"Error fetching orders: {e}")
        return jsonify([])


@app.route('/api/account')
def get_account():
    """Get Alpaca account info."""
    try:
        account = alpaca_broker.get_account()

        INITIAL_CAPITAL = 100_000.0  # Capital inicial de la cuenta

        return jsonify({
            'equity': round(float(account.get('equity', 0)), 2),
            'last_equity': round(float(account.get('last_equity', 0)), 2),
            'initial_capital': INITIAL_CAPITAL,
            'cash': round(float(account.get('cash', 0)), 2),
            'buying_power': round(float(account.get('buying_power', 0)), 2),
            'portfolio_value': round(float(account.get('portfolio_value', 0)), 2),
            'day_trade_count': account.get('daytrade_count', 0),
            'pattern_day_trader': account.get('pattern_day_trader', False),
            'trading_blocked': account.get('trading_blocked', False),
            'timestamp': datetime.now().isoformat(),
        })
    except Exception as e:
        logger.error(f"Error fetching account: {e}")
        return jsonify({'error': str(e)})


@app.route('/api/trades')
def get_trades():
    """Get recent trades."""
    trades = state['trades'][-50:]  # Last 50 trades
    return jsonify(trades)


def _get_alpaca_fills_for_date(target_date=None):
    """
    Fetch ALL fill activities from Alpaca for a given date using paginated
    /v2/account/activities/FILL (max 100/page). Captures every fill regardless
    of how many trades ran that day.

    Returns: {symbol: [{'side','qty','price','transaction_time','order_id'}, ...]}
    """
    import requests as _req

    if target_date is None:
        target_date = datetime.utcnow().date()

    after_ts = f"{target_date}T00:00:00Z"
    until_ts = f"{target_date}T23:59:59Z"

    headers = {
        "APCA-API-KEY-ID": config.alpaca.api_key,
        "APCA-API-SECRET-KEY": config.alpaca.secret_key,
    }

    all_activities = []
    page_token = None
    MAX_PAGES = 50  # safety cap

    for _ in range(MAX_PAGES):
        params = {
            "after":      after_ts,
            "until":      until_ts,
            "direction":  "asc",
            "page_size":  100,
        }
        if page_token:
            params["page_token"] = page_token

        try:
            resp = _req.get(
                f"{config.alpaca.base_url}/v2/account/activities/FILL",
                headers=headers,
                params=params,
                timeout=15,
            )
            if resp.status_code != 200:
                logger.warning(f"Activities FILL {resp.status_code}: {resp.text[:200]}")
                break
            data = resp.json()
            if not isinstance(data, list) or not data:
                break
            all_activities.extend(data)
            if len(data) < 100:
                break  # last page
            # Advance cursor: use last item's id as page_token
            last_id = data[-1].get("id", "")
            if last_id:
                page_token = last_id
            else:
                # Fallback: advance 'after' to last item's timestamp
                last_ts = data[-1].get("transaction_time", "")
                if last_ts:
                    after_ts = last_ts
                else:
                    break
        except Exception as e:
            logger.warning(f"Activities fetch error: {e}")
            break

    # Group by symbol
    fills_by_sym = {}
    for act in all_activities:
        if not isinstance(act, dict):
            continue
        sym   = act.get("symbol", "")
        price = float(act.get("price") or 0)
        qty   = float(act.get("qty") or 0)
        ts    = act.get("transaction_time", "")
        raw_side = act.get("side", "")
        # Normalize Alpaca side values: sell_short → sell, buy_to_cover → buy
        if raw_side in ("sell_short", "sell"):
            side = "sell"
        elif raw_side in ("buy_to_cover", "buy"):
            side = "buy"
        else:
            side = raw_side
        if sym and price > 0 and qty > 0 and side:
            fills_by_sym.setdefault(sym, []).append({
                "side":             side,
                "qty":              qty,
                "price":            price,
                "transaction_time": ts,
                "order_id":         act.get("order_id", ""),
            })

    logger.info(f"Fetched {len(all_activities)} fill activities for {target_date} "
                f"across {len(fills_by_sym)} symbols")
    return fills_by_sym


def _reconstruct_trades_fifo(sym_fills):
    """
    Reconstruct completed round-trip trades from a list of fills using FIFO matching.
    Handles LONG (buy→sell) and SHORT (sell→buy) correctly.

    Returns list of dicts: {action, entry_price, exit_price, qty, pnl,
                             entry_ts, exit_ts}
    """
    fills = sorted(sym_fills, key=lambda x: x["transaction_time"])

    position_qty = 0.0   # positive = net long, negative = net short
    open_lots    = []    # {'qty', 'price', 'ts', 'direction'} FIFO queue
    completed    = []

    for fill in fills:
        side  = fill["side"]   # 'buy' or 'sell'
        qty   = float(fill["qty"])
        price = float(fill["price"])
        ts    = fill["transaction_time"]

        if side == "buy":
            if position_qty >= 0:
                # Adding to (or opening) a long position
                open_lots.append({"qty": qty, "price": price, "ts": ts})
                position_qty += qty
            else:
                # Covering a short position
                remaining = qty
                while remaining > 0.001 and open_lots:
                    lot       = open_lots[0]
                    cover_qty = min(lot["qty"], remaining)
                    pnl       = (lot["price"] - price) * cover_qty  # short: entry_sell - cover_buy
                    completed.append({
                        "action":       "SHORT",
                        "entry_price":  lot["price"],
                        "exit_price":   price,
                        "qty":          cover_qty,
                        "pnl":          round(pnl, 2),
                        "entry_ts":     lot["ts"],
                        "exit_ts":      ts,
                    })
                    lot["qty"] -= cover_qty
                    if lot["qty"] < 0.001:
                        open_lots.pop(0)
                    remaining -= cover_qty
                position_qty += qty
                if remaining > 0.001:
                    # Flipped to long after covering
                    open_lots.append({"qty": remaining, "price": price, "ts": ts})

        elif side == "sell":
            if position_qty <= 0:
                # Adding to (or opening) a short position
                open_lots.append({"qty": qty, "price": price, "ts": ts})
                position_qty -= qty
            else:
                # Closing a long position
                remaining = qty
                while remaining > 0.001 and open_lots:
                    lot      = open_lots[0]
                    sell_qty = min(lot["qty"], remaining)
                    pnl      = (price - lot["price"]) * sell_qty  # long: exit_sell - entry_buy
                    completed.append({
                        "action":       "LONG",
                        "entry_price":  lot["price"],
                        "exit_price":   price,
                        "qty":          sell_qty,
                        "pnl":          round(pnl, 2),
                        "entry_ts":     lot["ts"],
                        "exit_ts":      ts,
                    })
                    lot["qty"] -= sell_qty
                    if lot["qty"] < 0.001:
                        open_lots.pop(0)
                    remaining -= sell_qty
                position_qty -= qty
                if remaining > 0.001:
                    # Flipped to short after selling all long
                    open_lots.append({"qty": remaining, "price": price, "ts": ts})

    return completed


def _enrich_exit_from_fills(ticker, action, exit_ts, fills_by_sym, window_sec=900):
    """
    Try to find a matching Alpaca fill for a reconciled trade.
    Returns (exit_price, qty) or (0, 0) if not found.
    """
    sym_fills = fills_by_sym.get(ticker, [])
    if not sym_fills or not exit_ts:
        return 0, 0
    closing_side = "sell" if action in ("LONG", "BUY") else "buy"
    try:
        exit_dt = datetime.fromisoformat(exit_ts[:19].replace("Z", ""))
    except Exception:
        return 0, 0
    best, best_diff = None, float("inf")
    for f in sym_fills:
        if f["side"] != closing_side:
            continue
        try:
            fill_dt = datetime.fromisoformat(f["transaction_time"][:19].replace("Z", ""))
            diff = abs((fill_dt - exit_dt).total_seconds())
            if diff < best_diff:
                best_diff = diff
                best = f
        except Exception:
            continue
    if best and best_diff <= window_sec:
        return best["price"], best["qty"]
    return 0, 0


def _load_daily_claude_logs():
    """
    Load today's trade log from claude_trader daily JSON log.
    Returns list of close records enriched from Alpaca fills.
    """
    logs_dir = os.path.join(_parent_dir, "logs")
    today = datetime.now().strftime("%Y%m%d")
    path = os.path.join(logs_dir, f"trades_{today}.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return []


@app.route('/api/trade_history')
def get_trade_history():
    """
    Transaction history combining two authoritative sources:

      Source 1 — trade_history.json: historical closed trades (all dates).
      Source 2 — Alpaca /v2/account/activities/FILL: ALL of today's fills,
                 paginated (max 100/page), FIFO-matched for LONG and SHORT.

    Source 2 is the ground truth for today's PnL. Source 1 provides history
    and Claude metadata for older trades. Dedup is by exit timestamp ±60s.
    """
    try:
        limit = request.args.get('limit', 200, type=int)

        # ── Source 1: historical closed trades from trade_history.json ────────
        history_path = os.path.join(_parent_dir, 'memory', 'trade_history.json')
        trades_dict = {}
        if os.path.exists(history_path):
            with open(history_path) as f:
                raw = json.load(f)
            trades_dict = raw.get('trades', {})

        # ── Source 2: ALL of today's fills from Alpaca activities (paginated) ─
        today_fills_by_sym = _get_alpaca_fills_for_date()

        result = []
        # Store exit datetimes from Source 1 to dedup Source 2
        s1_exit_dts = []

        # ── Build Source 1 records ─────────────────────────────────────────────
        for trade_id, t in trades_dict.items():
            if not isinstance(t, dict) or t.get('status') != 'closed':
                continue

            ticker      = t.get('ticker', '')
            action      = t.get('action', 'LONG')
            entry_price = float(t.get('entry_price') or t.get('actual_entry') or 0)
            exit_price  = float(t.get('exit_price') or 0)
            pnl_total   = float(t.get('pnl_usd') or 0)
            qty         = abs(float(t.get('qty') or t.get('quantity') or 0))
            exit_ts     = (t.get('exit_timestamp') or '').rstrip('Z').replace('Z', '')
            entry_ts    = (t.get('timestamp') or '').rstrip('Z').replace('Z', '')

            # Try to enrich exit_price from today's Alpaca fills
            if exit_price == 0:
                ep, fq = _enrich_exit_from_fills(ticker, action, exit_ts, today_fills_by_sym)
                if ep > 0:
                    exit_price = ep
                    if qty == 0 and fq > 0:
                        qty = fq

            # Derive qty from pnl math when missing
            if qty == 0 and entry_price > 0 and exit_price > 0 and pnl_total != 0:
                diff = (exit_price - entry_price) if action in ('LONG', 'BUY') else (entry_price - exit_price)
                if abs(diff) > 0.001:
                    implied = pnl_total / diff
                    if 0 < implied < 100000:
                        qty = round(implied, 2)

            # Recompute pnl from prices when reconciled pnl was 0
            if exit_price > 0 and entry_price > 0 and qty > 0 and pnl_total == 0:
                if action in ('LONG', 'BUY'):
                    pnl_total = round((exit_price - entry_price) * qty, 2)
                else:
                    pnl_total = round((entry_price - exit_price) * qty, 2)

            # Skip blank records (no exit data and no pnl)
            if exit_price == 0 and pnl_total == 0:
                continue

            pnl_pct = float(t.get('pnl_pct') or 0)
            if pnl_pct == 0 and entry_price > 0 and exit_price > 0:
                sign = 1 if action in ('LONG', 'BUY') else -1
                pnl_pct = round((exit_price / entry_price - 1) * 100 * sign, 2)

            qty = abs(qty)
            result.append({
                'id':             trade_id,
                'ticker':         ticker,
                'action':         action,
                'qty':            round(qty, 2) if qty else None,
                'entry_price':    round(entry_price, 4) if entry_price else None,
                'entry_total':    round(entry_price * qty, 2) if qty else None,
                'exit_price':     round(exit_price, 4) if exit_price else None,
                'exit_total':     round(exit_price * qty, 2) if (qty and exit_price) else None,
                'pnl_unit':       round(pnl_total / qty, 4) if qty else None,
                'pnl_total':      round(pnl_total, 2),
                'pnl_pct':        pnl_pct,
                'hold_hours':     round(float(t.get('hold_duration_hours') or 0), 1),
                'exit_reason':    t.get('exit_reason', ''),
                'timestamp':      entry_ts,
                'exit_timestamp': exit_ts,
                'source':         'claude_log',
            })

            # Track exit datetime for dedup
            try:
                s1_exit_dts.append(datetime.fromisoformat(exit_ts[:19]))
            except Exception:
                pass

        # ── Source 2: today's Alpaca fills → FIFO-reconstructed trades ────────
        seen_fill_ids = set()

        for sym, sym_fills in today_fills_by_sym.items():
            completed = _reconstruct_trades_fifo(sym_fills)

            for trade in completed:
                exit_ts_raw = trade['exit_ts'][:19].replace('Z', '')
                try:
                    exit_dt = datetime.fromisoformat(exit_ts_raw)
                except Exception:
                    continue

                # Dedup: skip if Source 1 has a trade within ±60s for same symbol
                is_dup = False
                for s1_dt in s1_exit_dts:
                    if abs((exit_dt - s1_dt).total_seconds()) <= 60:
                        is_dup = True
                        break
                if is_dup:
                    continue

                entry_ts_raw = trade['entry_ts'][:19].replace('Z', '')
                ep    = trade['entry_price']
                xp    = trade['exit_price']
                qty   = trade['qty']
                pnl   = trade['pnl']
                action = trade['action']

                pnl_pct = round((xp / ep - 1) * 100 * (1 if action == 'LONG' else -1), 2) if ep else 0

                try:
                    hold_h = round(
                        (exit_dt - datetime.fromisoformat(entry_ts_raw)).total_seconds() / 3600, 1
                    )
                except Exception:
                    hold_h = None

                fill_id = f"fill_{sym}_{exit_ts_raw.replace(':','').replace('-','')}"
                if fill_id in seen_fill_ids:
                    continue
                seen_fill_ids.add(fill_id)

                result.append({
                    'id':             fill_id,
                    'ticker':         sym,
                    'action':         action,
                    'qty':            round(qty, 2),
                    'entry_price':    round(ep, 4),
                    'entry_total':    round(ep * qty, 2),
                    'exit_price':     round(xp, 4),
                    'exit_total':     round(xp * qty, 2),
                    'pnl_unit':       round(pnl / qty, 4) if qty else None,
                    'pnl_total':      round(pnl, 2),
                    'pnl_pct':        pnl_pct,
                    'hold_hours':     hold_h,
                    'exit_reason':    'alpaca_fill',
                    'timestamp':      entry_ts_raw,
                    'exit_timestamp': exit_ts_raw,
                    'source':         'alpaca_activities',
                })

        # Sort by exit_timestamp desc, most recent first
        result.sort(key=lambda x: x.get('exit_timestamp') or x.get('timestamp') or '', reverse=True)
        return jsonify(result[:limit])

    except Exception as e:
        logger.error(f"Trade history error: {e}", exc_info=True)
        return jsonify([])


@app.route('/api/market/<ticker>')
def get_market_data(ticker):
    """Get current market data for ticker."""
    try:
        # Get latest quote
        end = datetime.now()
        start = end - timedelta(days=5)

        df = data_client.get_aggregates(
            ticker=ticker,
            multiplier=1,
            timespan='hour',
            from_date=start.strftime('%Y-%m-%d'),
            to_date=end.strftime('%Y-%m-%d')
        )

        if df.empty:
            return jsonify({'error': 'No data'}), 404

        # Compute features
        df = features_calc.compute_all(df)
        latest = df.iloc[-1]

        return jsonify({
            'ticker': ticker,
            'price': round(latest['close'], 2),
            'change_pct': round((latest['close'] / df['close'].iloc[-2] - 1) * 100, 2),
            'volume': int(latest['volume']),
            'rsi_14': round(latest.get('rsi_14', 50), 1),
            'macd': round(latest.get('macd', 0), 4),
            'sma_20': round(latest.get('sma_20', latest['close']), 2),
            'atr_14': round(latest.get('atr_14', 0), 2),
            'timestamp': latest.name.isoformat() if hasattr(latest.name, 'isoformat') else str(latest.name),
        })
    except Exception as e:
        logger.error(f"Market data error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/chart/<ticker>')
def get_chart_data(ticker):
    """Get weekly chart data for ticker (6 months)."""
    try:
        end = datetime.now()
        start = end - timedelta(days=180)

        df = data_client.get_aggregates(
            ticker=ticker,
            multiplier=1,
            timespan='week',
            from_date=start.strftime('%Y-%m-%d'),
            to_date=end.strftime('%Y-%m-%d')
        )

        if df.empty:
            return jsonify({'error': 'No data'}), 404

        chart_data = []
        for ts, row in df.iterrows():
            week_num = ts.isocalendar()[1] if hasattr(ts, 'isocalendar') else ts.to_pydatetime().isocalendar()[1]
            chart_data.append({
                'timestamp': f"W{week_num}",
                'close': round(row['close'], 2),
            })

        return jsonify(chart_data)
    except Exception as e:
        logger.error(f"Chart data error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/grok_signal')
def get_grok_signal():
    """Return latest Grok analysis + live news + SPY technicals."""
    try:
        # 1. Last Grok output
        history_path = os.path.join(_parent_dir, 'logs', 'grok_conversation_history.json')
        grok_last = {}
        if os.path.exists(history_path):
            with open(history_path) as f:
                history = json.load(f)
            if history:
                grok_last = history[-1]

        # 2. Live news from Alpaca
        news_items = []
        try:
            import requests as req
            api_key = alpaca_broker.api_key
            secret_key = alpaca_broker.secret_key
            resp = req.get(
                'https://data.alpaca.markets/v1beta1/news',
                headers={'APCA-API-KEY-ID': api_key, 'APCA-API-SECRET-KEY': secret_key},
                params={'sort': 'desc', 'limit': 8},
                timeout=8,
            )
            if resp.status_code == 200:
                for item in resp.json().get('news', []):
                    symbols = item.get('symbols', [])[:3]
                    news_items.append({
                        'headline': item.get('headline', ''),
                        'source': item.get('source', ''),
                        'time': item.get('created_at', '')[:16].replace('T', ' '),
                        'symbols': symbols,
                    })
        except Exception as e:
            logger.warning(f'News fetch failed: {e}')

        # 3. SPY technicals
        spy_tech = {}
        try:
            end = datetime.now()
            start = end - timedelta(days=5)
            df = data_client.get_aggregates('SPY', 1, 'hour',
                                            start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))
            if not df.empty:
                df = features_calc.compute_all(df)
                latest = df.iloc[-1]
                prev = df.iloc[-2]
                def safe(val, default=0, dec=3):
                    try:
                        v = float(val)
                        return round(v, dec) if not (v != v) else default  # NaN check
                    except Exception:
                        return default

                spy_tech = {
                    'price': safe(latest['close'], dec=2),
                    'change_pct': safe((latest['close'] / prev['close'] - 1) * 100, dec=2),
                    'rsi_14': safe(latest.get('rsi_14', 50), 50, dec=1),
                    'macd': safe(latest.get('macd', 0), dec=3),
                    'macd_signal': safe(latest.get('macd_signal', 0), dec=3),
                    'macd_hist': safe(latest.get('macd_histogram', 0), dec=3),
                    'sma_20': safe(latest.get('sma_20', latest['close']), dec=2),
                    'sma_50': safe(latest.get('sma_50', latest['close']), dec=2),
                    'bb_pct_b': safe(latest.get('bb_pct_b', 0.5), 0.5, dec=3),
                    'atr_14': safe(latest.get('atr_14', 0), dec=2),
                    'adx': safe(latest.get('adx', 0), 0, dec=1),
                    'volume_ratio': safe(latest.get('volume_ratio_20', 1), 1, dec=2),
                    'trend': 'BULLISH' if latest['close'] > safe(latest.get('sma_20', latest['close'])) else 'BEARISH',
                    'macd_cross': 'BULLISH' if safe(latest.get('macd', 0)) > safe(latest.get('macd_signal', 0)) else 'BEARISH',
                }
        except Exception as e:
            logger.warning(f'SPY technicals failed: {e}')

        return jsonify({
            'timestamp': grok_last.get('timestamp', ''),
            'market_assessment': grok_last.get('market_assessment', ''),
            'strategy_rationale': grok_last.get('strategy_rationale', ''),
            'lessons_applied': grok_last.get('lessons_applied', ''),
            'avoid_tickers': grok_last.get('avoid_tickers', []),
            'avoid_reasons': grok_last.get('avoid_reasons', ''),
            'selections': grok_last.get('selections', []),
            'news': news_items,
            'spy_technicals': spy_tech,
        })
    except Exception as e:
        logger.error(f'Grok signal error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/daily_pnl_reconcile')
def get_daily_pnl_reconcile():
    """
    Compare Alpaca's authoritative equity delta for today vs what the
    dashboard reconstructs from fills. Useful for spotting discrepancies.
    """
    try:
        import requests as _req
        headers = {
            "APCA-API-KEY-ID":     config.alpaca.api_key,
            "APCA-API-SECRET-KEY": config.alpaca.secret_key,
        }

        # Use account API: last_equity = yesterday's close, equity = current
        account      = alpaca_broker.get_account()
        alpaca_start = round(float(account.get('last_equity', 0)), 2)
        alpaca_end   = round(float(account.get('equity', 0)), 2)
        alpaca_delta = round(alpaca_end - alpaca_start, 2)

        # Reconstruct today's fill-based PnL
        fills_by_sym   = _get_alpaca_fills_for_date()
        total_fill_pnl = 0.0
        fill_count     = 0
        by_symbol      = {}

        for sym, sym_fills in fills_by_sym.items():
            completed = _reconstruct_trades_fifo(sym_fills)
            sym_pnl   = sum(t['pnl'] for t in completed)
            total_fill_pnl += sym_pnl
            fill_count     += len(completed)
            if completed:
                by_symbol[sym] = {
                    'trades': len(completed),
                    'pnl':    round(sym_pnl, 2),
                }

        # Current unrealized from open positions
        unrealized = 0.0
        try:
            positions = alpaca_broker.get_positions()
            unrealized = sum(float(p.get('unrealized_pl', 0)) for p in positions)
        except Exception:
            pass

        return jsonify({
            'alpaca_equity_start':        alpaca_start,
            'alpaca_equity_end':          alpaca_end,
            'alpaca_delta':               alpaca_delta,
            'fill_reconstructed_realized': round(total_fill_pnl, 2),
            'current_unrealized':         round(unrealized, 2),
            'fill_reconstructed_total':   round(total_fill_pnl + unrealized, 2),
            'discrepancy':                round(alpaca_delta - total_fill_pnl, 2) if alpaca_delta is not None else None,
            'total_closed_trades':        fill_count,
            'by_symbol':                  by_symbol,
        })
    except Exception as e:
        logger.error(f'Daily PnL reconcile error: {e}', exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/signals')
def get_signals():
    """Get current trading signals."""
    try:
        ticker = 'SPY'
        end = datetime.now()
        start = end - timedelta(days=3)

        df = data_client.get_aggregates(
            ticker=ticker,
            multiplier=1,
            timespan='hour',
            from_date=start.strftime('%Y-%m-%d'),
            to_date=end.strftime('%Y-%m-%d')
        )

        if df.empty:
            return jsonify({'signal': 'NEUTRAL', 'confidence': 0})

        df = features_calc.compute_all(df)
        latest = df.iloc[-1]

        # Simple signal logic
        rsi = latest.get('rsi_14', 50)
        macd = latest.get('macd', 0)
        signal_line = latest.get('macd_signal', 0)
        price = latest['close']
        sma20 = latest.get('sma_20', price)

        # Score components
        score = 0
        reasons = []

        if rsi < 30:
            score += 2
            reasons.append(f"RSI oversold ({rsi:.0f})")
        elif rsi > 70:
            score -= 2
            reasons.append(f"RSI overbought ({rsi:.0f})")
        elif rsi < 45:
            score += 1
        elif rsi > 55:
            score -= 1

        if macd > signal_line:
            score += 1
            reasons.append("MACD bullish")
        else:
            score -= 1
            reasons.append("MACD bearish")

        if price > sma20:
            score += 1
            reasons.append("Price > SMA20")
        else:
            score -= 1
            reasons.append("Price < SMA20")

        # Determine signal
        if score >= 2:
            signal = 'LONG'
            confidence = min(90, 50 + score * 10)
        elif score <= -2:
            signal = 'SHORT'
            confidence = min(90, 50 + abs(score) * 10)
        else:
            signal = 'NEUTRAL'
            confidence = 50

        return jsonify({
            'signal': signal,
            'confidence': confidence,
            'score': score,
            'reasons': reasons,
            'price': round(price, 2),
            'timestamp': datetime.now().isoformat(),
        })
    except Exception as e:
        logger.error(f"Signals error: {e}")
        return jsonify({'signal': 'ERROR', 'confidence': 0, 'error': str(e)})


@app.route('/api/daily_metrics')
def get_daily_metrics():
    """Get today's closed trade metrics from trade_history.json."""
    try:
        history_path = os.path.join(_parent_dir, 'memory', 'trade_history.json')
        today = datetime.now().date().isoformat()
        trades_today = []

        if os.path.exists(history_path):
            with open(history_path) as f:
                data = json.load(f)
            for t in data.get('trades', {}).values():
                if t.get('status') != 'closed':
                    continue
                # Match by exit_timestamp or timestamp date
                ts = t.get('exit_timestamp') or t.get('timestamp', '')
                if ts[:10] == today:
                    trades_today.append(float(t.get('pnl_usd', 0) or 0))

        n = len(trades_today)
        realized = sum(trades_today)
        wins = [p for p in trades_today if p > 0]
        losses = [p for p in trades_today if p <= 0]
        win_rate = round(len(wins) / n * 100, 1) if n else 0
        avg_pnl = round(realized / n, 2) if n else 0
        best = round(max(trades_today), 2) if trades_today else 0
        worst = round(min(trades_today), 2) if trades_today else 0

        # Live unrealized from Alpaca
        unrealized = 0
        try:
            positions = alpaca_broker.get_positions()
            unrealized = sum(float(p.get('unrealized_pl', 0)) for p in positions)
        except Exception:
            pass

        return jsonify({
            'date': today,
            'total_trades': n,
            'win_rate': win_rate,
            'realized_pnl': round(realized, 2),
            'avg_pnl': avg_pnl,
            'best_trade': best,
            'worst_trade': worst,
            'unrealized_pnl': round(unrealized, 2),
        })
    except Exception as e:
        logger.error(f'Daily metrics error: {e}')
        return jsonify({'total_trades': 0, 'win_rate': 0, 'realized_pnl': 0,
                        'avg_pnl': 0, 'best_trade': 0, 'worst_trade': 0, 'unrealized_pnl': 0})


@app.route('/api/metrics')
def get_metrics():
    """Get performance metrics."""
    trades = state['trades']

    if not trades:
        return jsonify({
            'total_trades': 0,
            'win_rate': 0,
            'profit_factor': 0,
            'sharpe_ratio': 0,
            'avg_trade_pnl': 0,
        })

    df = pd.DataFrame(trades)

    winning = df[df['pnl'] > 0]
    losing = df[df['pnl'] <= 0]

    win_rate = len(winning) / len(df) * 100
    total_win = winning['pnl'].sum() if len(winning) > 0 else 0
    total_loss = abs(losing['pnl'].sum()) if len(losing) > 0 else 0.01
    profit_factor = total_win / total_loss

    # Sharpe (simplified)
    returns = df['pnl'].values / state['initial_capital']
    sharpe = np.mean(returns) / (np.std(returns) + 1e-6) * np.sqrt(252)

    return jsonify({
        'total_trades': len(df),
        'win_rate': round(win_rate, 1),
        'profit_factor': round(profit_factor, 2),
        'sharpe_ratio': round(sharpe, 2),
        'avg_trade_pnl': round(df['pnl'].mean(), 2),
        'best_trade': round(df['pnl'].max(), 2),
        'worst_trade': round(df['pnl'].min(), 2),
        'long_trades': len(df[df['direction'] == 'LONG']),
        'short_trades': len(df[df['direction'] == 'SHORT']),
    })


@app.route('/api/equity')
def get_equity_curve():
    """Get real weekly equity curve from Alpaca portfolio history."""
    try:
        raw = alpaca_broker._make_request('GET', '/v2/account/portfolio/history', {
            'period': '6M', 'timeframe': '1D',
        })

        timestamps_unix = raw.get('timestamp', [])
        equities = raw.get('equity', [])

        if not timestamps_unix or not equities:
            raise ValueError("No portfolio history data")

        # Build daily series
        daily = []
        for ts, eq in zip(timestamps_unix, equities):
            if eq is None:
                continue
            dt = datetime.utcfromtimestamp(ts)
            daily.append({'dt': dt, 'equity': eq})

        # Resample to weekly: keep the LAST value of each ISO week
        weekly_map = {}  # key = (year, week) → last entry
        for d in daily:
            key = d['dt'].isocalendar()[:2]  # (year, week_number)
            weekly_map[key] = d  # overwrites → last day of week wins

        weekly = sorted(weekly_map.values(), key=lambda x: x['dt'])

        # Always append current live equity as the latest point
        account = alpaca_broker.get_account()
        current_equity = float(account.get('equity', weekly[-1]['equity'] if weekly else 100000))
        weekly.append({'dt': datetime.utcnow(), 'equity': current_equity})

        return jsonify({
            'timestamps': [f"W{w['dt'].isocalendar()[1]}" for w in weekly],
            'equity': [round(w['equity'], 2) for w in weekly],
        })

    except Exception as e:
        logger.error(f"Equity curve error: {e}")
        return jsonify({'timestamps': [], 'equity': []})


# Simulate some trading data for demo
def simulate_demo_data():
    """Generate demo trading data."""
    import random

    initial = 100000
    equity = [initial]
    trades = []

    # Generate 30 demo trades
    for i in range(30):
        direction = random.choice(['LONG', 'SHORT'])
        entry = 680 + random.uniform(-10, 10)
        pnl_pct = random.gauss(0.001, 0.015)  # Avg 0.1% gain, 1.5% std
        exit_price = entry * (1 + pnl_pct) if direction == 'LONG' else entry * (1 - pnl_pct)
        shares = int(equity[-1] * 0.25 / entry)
        pnl = shares * (exit_price - entry) * (1 if direction == 'LONG' else -1)

        trades.append({
            'id': i + 1,
            'direction': direction,
            'entry_price': round(entry, 2),
            'exit_price': round(exit_price, 2),
            'shares': shares,
            'pnl': round(pnl, 2),
            'pnl_pct': round(pnl_pct * 100, 2),
            'timestamp': (datetime.now() - timedelta(hours=30-i)).isoformat(),
        })

        equity.append(equity[-1] + pnl)

    state['trades'] = trades
    state['equity_curve'] = equity
    state['last_update'] = datetime.now().isoformat()


if __name__ == '__main__':
    # Generate demo data
    simulate_demo_data()

    print("\n" + "="*50)
    print("STOCK MARKET ALGORITHM - DASHBOARD")
    print("="*50)
    print(f"Starting server on http://localhost:5002")
    print("="*50 + "\n")

    app.run(host='0.0.0.0', port=5002, debug=True)
