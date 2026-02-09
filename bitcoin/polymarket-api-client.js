#!/usr/bin/env node

/**
 * Polymarket API Client - Bitcoin 15m Market Monitor
 * Uses official Polymarket APIs for real-time data
 */

const https = require('https');

class PolymarketClient {
  constructor() {
    this.gammaApi = 'https://gamma-api.polymarket.com';
    this.clobApi = 'https://clob.polymarket.com';
    this.dataApi = 'https://data-api.polymarket.com';
  }

  /**
   * Fetch markets by search/filter
   * Gamma API: GET /events, /markets
   */
  async fetchMarketsGamma(query = 'btc-up-or-down-15m') {
    const endpoint = `/events?slug=${encodeURIComponent(query)}`;
    return this._request(this.gammaApi, endpoint);
  }

  /**
   * Fetch market with active orderbook
   * CLOB API: GET /markets/{id}
   */
  async fetchMarketClob(marketId) {
    const endpoint = `/markets/${marketId}`;
    return this._request(this.clobApi, endpoint);
  }

  /**
   * Fetch orderbook with best bid/ask
   * CLOB API: GET /orderbook/{tokenId}
   */
  async fetchOrderbook(tokenId) {
    const endpoint = `/orderbook/${tokenId}`;
    return this._request(this.clobApi, endpoint);
  }

  /**
   * Get price and odds for a market
   * CLOB API: GET /prices?market_id=...
   */
  async fetchPrices(marketId) {
    const endpoint = `/prices?market_id=${marketId}`;
    return this._request(this.clobApi, endpoint);
  }

  /**
   * Fetch user positions
   * Data API: GET /user/{address}
   */
  async fetchUserPositions(address) {
    const endpoint = `/user/${address}`;
    return this._request(this.dataApi, endpoint);
  }

  /**
   * Helper: Make HTTPS request
   */
  _request(baseUrl, endpoint) {
    return new Promise((resolve, reject) => {
      const url = new URL(baseUrl + endpoint);
      
      https.get(url, { 
        headers: { 'User-Agent': 'PolymarketBTCMonitor/1.0' } 
      }, (res) => {
        let data = '';
        res.on('data', chunk => data += chunk);
        res.on('end', () => {
          try {
            resolve(JSON.parse(data));
          } catch (e) {
            reject(new Error(`JSON parse error: ${e.message}`));
          }
        });
      }).on('error', reject);
    });
  }
}

/**
 * Main monitoring function
 */
async function monitorBTCMarket() {
  const client = new PolymarketClient();
  
  try {
    console.log('🔍 Fetching BTC 15m markets from Gamma API...');
    
    // Step 1: Discover BTC markets
    const markets = await client.fetchMarketsGamma('btc-up-or-down-15m');
    
    if (!markets || markets.length === 0) {
      console.error('❌ No BTC markets found');
      return;
    }
    
    const market = markets[0];
    console.log(`✅ Found market: ${market.title}`);
    console.log(`   ID: ${market.id}`);
    console.log(`   Status: ${market.active ? 'ACTIVE' : 'INACTIVE'}`);
    
    // Step 2: Get current market data from CLOB
    if (market.markets && market.markets.length > 0) {
      const clobMarket = market.markets[0];
      const tokenIds = JSON.parse(clobMarket.clobTokenIds);
      
      console.log('\n📊 Fetching live prices from CLOB API...');
      
      // Fetch orderbook for both outcomes
      for (let i = 0; i < tokenIds.length; i++) {
        const tokenId = tokenIds[i];
        const outcome = i === 0 ? 'UP' : 'DOWN';
        
        try {
          const orderbook = await client.fetchOrderbook(tokenId);
          
          if (orderbook.bids && orderbook.asks) {
            const bestBid = orderbook.bids[0]?.price || 'N/A';
            const bestAsk = orderbook.asks[0]?.price || 'N/A';
            const midPrice = ((parseFloat(bestBid) + parseFloat(bestAsk)) / 2).toFixed(4);
            
            console.log(`\n🔹 ${outcome}:`);
            console.log(`   Best Bid: ${bestBid}`);
            console.log(`   Best Ask: ${bestAsk}`);
            console.log(`   Mid Price: ${midPrice}`);
          }
        } catch (e) {
          console.error(`❌ Error fetching ${outcome} orderbook:`, e.message);
        }
      }
    }
    
    // Step 3: Parse outcome prices (if available)
    if (market.markets && market.markets[0]) {
      const m = market.markets[0];
      const prices = JSON.parse(m.outcomePrices);
      const outcomes = JSON.parse(m.outcomes);
      
      console.log('\n💹 **Current Market Odds:**');
      outcomes.forEach((outcome, idx) => {
        const prob = parseFloat(prices[idx]);
        console.log(`   ${outcome}: ${(prob * 100).toFixed(1)}%`);
      });
      
      console.log(`\n   Liquidity: $${parseFloat(m.liquidityNum).toLocaleString()}`);
      console.log(`   Volume: $${parseFloat(m.volumeNum).toLocaleString()}`);
      console.log(`   Expires: ${new Date(m.endDate).toLocaleString()}`);
    }
    
  } catch (error) {
    console.error('❌ Error:', error.message);
  }
}

// Run if executed directly
if (require.main === module) {
  monitorBTCMarket();
}

module.exports = { PolymarketClient };
