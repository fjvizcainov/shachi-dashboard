# Shachi Trading System Dashboard

🐋 **V5 Simplified Trading System with Alpaca + Grok AI**

Live Dashboard: [https://fjvizcainov.github.io/shachi-dashboard/](https://fjvizcainov.github.io/shachi-dashboard/)

## Features

- **Real-time Alpaca Integration** - Live positions, orders, and account data
- **Grok AI Signals** - Intelligent trade recommendations
- **Paper Trading** - Safe testing environment
- **12 Proven Features** - Simplified from 130+ in earlier versions
- **Trailing Stop Exits** - Primary exit strategy

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    GitHub Pages                              │
│                  (Static Dashboard)                          │
│          fjvizcainov.github.io/shachi-dashboard              │
└────────────────────────┬────────────────────────────────────┘
                         │ API Calls
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    Render.com                                │
│                   (API Server)                               │
│              shachi-api.onrender.com                         │
└────────────────────────┬────────────────────────────────────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
    ┌──────────┐   ┌──────────┐   ┌──────────┐
    │  Alpaca  │   │   Grok   │   │ Polygon  │
    │   API    │   │    AI    │   │   API    │
    └──────────┘   └──────────┘   └──────────┘
```

## Deployment

### 1. Deploy API to Render

1. Fork this repository
2. Go to [render.com](https://render.com) and create account
3. Click "New" → "Blueprint"
4. Connect your GitHub repo
5. Add environment variables:
   - `ALPACA_API_KEY` - Your Alpaca paper trading API key
   - `ALPACA_SECRET_KEY` - Your Alpaca secret key
6. Deploy!

Your API will be available at: `https://shachi-api.onrender.com`

### 2. Update Dashboard

After deploying the API, update `index.html` line 416:
```javascript
const API_BASE = 'https://YOUR-APP-NAME.onrender.com';
```

### 3. Enable GitHub Pages

1. Go to repo Settings → Pages
2. Source: Deploy from branch `main`
3. Your dashboard is live at: `https://fjvizcainov.github.io/shachi-dashboard/`

## Configuration

### V5 Simplified Settings

| Parameter | Value | Description |
|-----------|-------|-------------|
| Leverage | 1.0x | No leverage until edge proven |
| Long Threshold | z > 1.2 | More selective entries |
| Short Threshold | z < -1.5 | Asymmetric short threshold |
| Stop Loss | 3.5x ATR | Emergency exit only |
| Trailing Activation | +1.5% | Start trailing at 1.5% profit |
| Trailing Distance | 1.5x ATR | Dynamic trailing stop |

### 12 Features (Proven Edge)

**Microstructure (6)**
- kyle_lambda_12h
- volume_imbalance_6h
- ofi_proxy_6h
- micro_score
- cs_spread_6h
- depth_proxy_6h

**Volatility/Regime (3)**
- atr_24h
- parkinson_vol_24h
- vol_regime_score

**Momentum (3)**
- ret_6h
- ret_24h
- price_vs_vwap

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| GET /api/status | System status |
| GET /api/account | Alpaca account info |
| GET /api/positions | Current positions |
| GET /api/orders | Pending orders |
| GET /api/signals | Current trading signals |
| GET /api/health | Health check |

## Local Development

```bash
# Clone repo
git clone https://github.com/fjvizcainov/shachi-dashboard.git
cd shachi-dashboard

# Set environment variables
export ALPACA_API_KEY=your_key
export ALPACA_SECRET_KEY=your_secret

# Run API locally
cd api
pip install -r requirements.txt
python server.py

# Dashboard will connect to localhost:5002
```

## Realistic Expectations

| Metric | Range |
|--------|-------|
| Direction Accuracy | 51-55% |
| Win Rate | 45-55% |
| Profit Factor | 1.1-1.3 |
| Monthly Return | 0.5-2% |
| Max Drawdown | 15-25% |

## License

MIT
