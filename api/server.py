"""
Shachi Trading System - API Server
Alpaca Paper Trading + Grok AI Integration

Deploy to Render.com or similar platform.
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import os
import requests
from datetime import datetime
import logging

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Alpaca Configuration
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

# Headers for Alpaca API
def get_alpaca_headers():
    return {
        "APCA-API-KEY-ID": ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
        "Content-Type": "application/json"
    }


@app.route('/')
def index():
    return jsonify({
        "service": "Shachi Trading API",
        "version": "5.0.0",
        "status": "running",
        "endpoints": ["/api/status", "/api/account", "/api/positions", "/api/orders", "/api/signals"]
    })


@app.route('/api/status')
def get_status():
    """Get system status."""
    return jsonify({
        'status': 'running',
        'mode': 'paper',
        'last_update': datetime.now().isoformat(),
        'uptime_hours': 24,
        'alpaca_configured': bool(ALPACA_API_KEY and ALPACA_SECRET_KEY),
    })


@app.route('/api/account')
def get_account():
    """Get Alpaca account info."""
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        return jsonify({'error': 'Alpaca API keys not configured'}), 500

    try:
        response = requests.get(
            f"{ALPACA_BASE_URL}/v2/account",
            headers=get_alpaca_headers(),
            timeout=10
        )
        response.raise_for_status()
        account = response.json()

        return jsonify({
            'equity': round(float(account.get('equity', 0)), 2),
            'cash': round(float(account.get('cash', 0)), 2),
            'buying_power': round(float(account.get('buying_power', 0)), 2),
            'portfolio_value': round(float(account.get('portfolio_value', 0)), 2),
            'day_trade_count': account.get('daytrade_count', 0),
            'pattern_day_trader': account.get('pattern_day_trader', False),
            'trading_blocked': account.get('trading_blocked', False),
            'timestamp': datetime.now().isoformat(),
        })
    except requests.exceptions.RequestException as e:
        logger.error(f"Alpaca account error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/positions')
def get_positions():
    """Get current positions from Alpaca."""
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        return jsonify([])

    try:
        response = requests.get(
            f"{ALPACA_BASE_URL}/v2/positions",
            headers=get_alpaca_headers(),
            timeout=10
        )
        response.raise_for_status()
        positions = response.json()

        result = []
        for pos in positions:
            qty = int(pos.get('qty', 0))
            entry_price = float(pos.get('avg_entry_price', 0))
            current_price = float(pos.get('current_price', entry_price))
            market_value = float(pos.get('market_value', 0))
            unrealized_pl = float(pos.get('unrealized_pl', 0))
            unrealized_plpc = float(pos.get('unrealized_plpc', 0)) * 100

            result.append({
                'symbol': pos.get('symbol', ''),
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
    except requests.exceptions.RequestException as e:
        logger.error(f"Alpaca positions error: {e}")
        return jsonify([])


@app.route('/api/orders')
def get_orders():
    """Get pending orders from Alpaca."""
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        return jsonify([])

    try:
        response = requests.get(
            f"{ALPACA_BASE_URL}/v2/orders",
            headers=get_alpaca_headers(),
            params={"status": "open", "limit": 20},
            timeout=10
        )
        response.raise_for_status()
        orders = response.json()

        result = []
        for order in orders:
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
    except requests.exceptions.RequestException as e:
        logger.error(f"Alpaca orders error: {e}")
        return jsonify([])


@app.route('/api/signals')
def get_signals():
    """Get current trading signals (simplified)."""
    # This would integrate with Grok AI in production
    # For now, return a placeholder signal
    return jsonify({
        'signal': 'NEUTRAL',
        'confidence': 50,
        'score': 0,
        'reasons': ['Market closed', 'Awaiting next signal'],
        'price': 0,
        'timestamp': datetime.now().isoformat(),
    })


@app.route('/api/health')
def health_check():
    """Health check endpoint for deployment."""
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5002))
    debug = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'

    logger.info(f"Starting Shachi API on port {port}")
    logger.info(f"Alpaca configured: {bool(ALPACA_API_KEY and ALPACA_SECRET_KEY)}")

    app.run(host='0.0.0.0', port=port, debug=debug)
