#!/usr/bin/env node
/**
 * Polymarket WebSocket Monitor for BTC 15-minute markets
 * Sends alerts to Clawdbot when significant price changes occur
 */

// No WebSocket required - using REST polling
const https = require('https');
const fs = require('fs');
const path = require('path');

// Configuration
const CONFIG = {
  // Polymarket WebSocket endpoints
  wsUrl: 'wss://ws-subscriptions-clob.polymarket.com/ws/market',
  rtdsUrl: 'wss://ws-live-data.polymarket.com',

  // Alert thresholds
  priceChangeThreshold: 0.10, // 10% change triggers alert
  volumeSpikeThreshold: 0.50, // 50% volume increase

  // Data storage
  dataDir: path.join(process.env.HOME, 'clawd/bitcoin/data'),

  // Telegram (via Clawdbot)
  telegramChatId: '7063125942',
};

// State
let lastOdds = { up: 0.5, down: 0.5 };
let lastVolume = 0;

// Get current 15-minute market slug
function getCurrentMarketSlug() {
  const ts = Math.floor(Date.now() / 1000 / 900) * 900;
  return `btc-updown-15m-${ts}`;
}

// Fetch current market data via REST (fallback)
async function fetchMarketData() {
  const slug = getCurrentMarketSlug();
  const url = `https://gamma-api.polymarket.com/events?slug=${slug}`;

  return new Promise((resolve, reject) => {
    https.get(url, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          const json = JSON.parse(data);
          if (json && json[0] && json[0].markets && json[0].markets[0]) {
            const market = json[0].markets[0];
            const prices = JSON.parse(market.outcomePrices);
            resolve({
              slug,
              up: parseFloat(prices[0]),
              down: parseFloat(prices[1]),
              volume: market.volume24hr || 0,
              liquidity: market.liquidity || 0,
            });
          } else {
            resolve(null);
          }
        } catch (e) {
          reject(e);
        }
      });
    }).on('error', reject);
  });
}

// Send alert via Clawdbot CLI
function sendAlert(message) {
  const { execSync } = require('child_process');
  try {
    execSync(`clawdbot message send --channel telegram --target "${CONFIG.telegramChatId}" --message "${message.replace(/"/g, '\\"')}"`, {
      stdio: 'inherit'
    });
    console.log('[ALERT SENT]', message);
  } catch (e) {
    console.error('[ALERT FAILED]', e.message);
  }
}

// Check for significant changes
function checkForAlerts(current) {
  const upChange = Math.abs(current.up - lastOdds.up);
  const downChange = Math.abs(current.down - lastOdds.down);

  // Price change alert
  if (upChange > CONFIG.priceChangeThreshold || downChange > CONFIG.priceChangeThreshold) {
    const direction = current.up > lastOdds.up ? '📈 UP' : '📉 DOWN';
    const message = `⚡ POLYMARKET SPIKE\\n${direction} odds moved ${(upChange * 100).toFixed(1)}%\\nAntes: UP ${(lastOdds.up * 100).toFixed(1)}% / DOWN ${(lastOdds.down * 100).toFixed(1)}%\\nAhora: UP ${(current.up * 100).toFixed(1)}% / DOWN ${(current.down * 100).toFixed(1)}%`;
    sendAlert(message);
  }

  // Volume spike alert
  if (lastVolume > 0 && current.volume > lastVolume * (1 + CONFIG.volumeSpikeThreshold)) {
    const message = `💰 VOLUME SPIKE\\nVolumen aumentó ${((current.volume / lastVolume - 1) * 100).toFixed(1)}%\\nAntes: $${lastVolume.toFixed(0)}\\nAhora: $${current.volume.toFixed(0)}`;
    sendAlert(message);
  }

  // Update state
  lastOdds = { up: current.up, down: current.down };
  lastVolume = current.volume;

  // Save to file
  const dataFile = path.join(CONFIG.dataDir, 'polymarket_realtime.json');
  fs.writeFileSync(dataFile, JSON.stringify({
    timestamp: new Date().toISOString(),
    ...current
  }, null, 2));
}

// Main polling loop (REST fallback since WS requires auth)
async function startPolling() {
  console.log('[POLYMARKET MONITOR] Starting...');
  console.log('[CONFIG] Price threshold:', CONFIG.priceChangeThreshold * 100 + '%');
  console.log('[CONFIG] Volume threshold:', CONFIG.volumeSpikeThreshold * 100 + '%');

  // Initial fetch
  try {
    const initial = await fetchMarketData();
    if (initial) {
      lastOdds = { up: initial.up, down: initial.down };
      lastVolume = initial.volume;
      console.log('[INITIAL]', `UP: ${(initial.up * 100).toFixed(1)}% | DOWN: ${(initial.down * 100).toFixed(1)}%`);
    }
  } catch (e) {
    console.error('[INIT ERROR]', e.message);
  }

  // Poll every 30 seconds
  setInterval(async () => {
    try {
      const data = await fetchMarketData();
      if (data) {
        console.log(`[${new Date().toISOString()}] UP: ${(data.up * 100).toFixed(1)}% | DOWN: ${(data.down * 100).toFixed(1)}% | Vol: $${data.volume.toFixed(0)}`);
        checkForAlerts(data);
      }
    } catch (e) {
      console.error('[POLL ERROR]', e.message);
    }
  }, 30000);
}

// Run
startPolling();
