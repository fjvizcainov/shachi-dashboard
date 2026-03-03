# Shachi Trading System Dashboard

🐋 **V5 Simplified Trading System**

A disciplined, simplified trading approach based on learnings from V1-V4:
- **12 features** with proven edge (vs 130+ in earlier versions)
- **Trailing stop** as primary exit strategy
- **No leverage** until edge is validated
- **Only OOS metrics** (walk-forward validation)

## Live Dashboard

Visit: [https://fjvizcainov.github.io/shachi-dashboard/](https://fjvizcainov.github.io/shachi-dashboard/)

## Key Principles

### Features (12 Total)
| Category | Count | Features |
|----------|-------|----------|
| Microstructure | 6 | kyle_lambda, volume_imbalance, ofi_proxy, micro_score, cs_spread, depth_proxy |
| Volatility/Regime | 3 | atr_24h, parkinson_vol, vol_regime_score |
| Momentum | 3 | ret_6h, ret_24h, price_vs_vwap |

### Configuration
- **Leverage**: 1.0x (none)
- **Long Threshold**: z-score > 1.2
- **Short Threshold**: z-score < -1.5
- **Stop Loss**: 3.5x ATR (emergency only)
- **Trailing Stop**: Activates at +1.5%, trails at 1.5x ATR

### Realistic Expectations
- Direction Accuracy: 51-55%
- Win Rate: 45-55%
- Profit Factor: 1.1-1.3
- Monthly Return: 0.5-2%
- Max Drawdown: 15-25%

## Architecture

```
v5/
├── features/
│   ├── micro.py       # Microstructure (6)
│   ├── regime.py      # Volatility/Regime (3)
│   └── momentum.py    # Momentum (3)
├── model/
│   └── predictor.py   # HistGradientBoosting
├── exits/
│   ├── trailing.py    # Primary exit
│   ├── stoploss.py    # Emergency exit
│   └── time_stop.py   # Time-based exits
└── risk/
    ├── position_sizer.py
    └── monitor.py     # Circuit breakers
```

## License

MIT
