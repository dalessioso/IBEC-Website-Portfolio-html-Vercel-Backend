from flask import Flask, jsonify
from flask_cors import CORS
import pandas as pd
import os
import requests
from datetime import datetime

app = Flask(__name__)
# Enable CORS so your frontend can talk to this API without security blocks
CORS(app)

# Hardcoded FMP API Key
API_KEY = "nljARgm0v27ktpQ3x7jIFBcZJmUJW3sz"

# Helper function to map suffixes to FMP FX pairs
def get_fx_pair(ticker):
    if ticker.endswith('.NS'): return 'INRUSD'
    if ticker.endswith('.MC'): return 'EURUSD'
    if ticker.endswith('.L'): return 'GBPUSD'
    return None

def fetch_fmp_historical_price(ticker, date_str):
    """Fetches the closing price for a specific date from FMP."""
    try:
        # FMP format requires YYYY-MM-DD
        target_date = pd.to_datetime(date_str).strftime('%Y-%m-%d')
        url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{ticker}?from={target_date}&to={target_date}&apikey={API_KEY}"
        
        response = requests.get(url).json()
        if 'historical' in response and len(response['historical']) > 0:
            return response['historical'][0]['close']
    except Exception as e:
        print(f"Failed to fetch history for {ticker}: {e}")
    return None

@app.route('/api', methods=['GET'])
def get_portfolio():
    try:
        # 1. Read the CSV
        csv_path = os.path.join(os.path.dirname(__file__), '..', 'trades.csv')
        
        if not os.path.exists(csv_path):
            return jsonify({"error": f"CRITICAL: trades.csv not found at {csv_path}"}), 404
            
        df = pd.read_csv(csv_path)
        
        if df.empty:
            return jsonify({"error": "CRITICAL: trades.csv was found but contains no data!"}), 400
            
        # Clean columns and dates
        df.columns = ['ticker', 'shares', 'purchase_date']
        df['purchase_date'] = pd.to_datetime(df['purchase_date'])
        
        # We only want active/past trades, no future trades
        today = pd.Timestamp.today().normalize()
        df = df[df['purchase_date'] <= today]
        
        # Get unique tickers and necessary FX pairs
        unique_tickers = df['ticker'].unique().tolist()
        fx_pairs = list(set([get_fx_pair(t) for t in unique_tickers if get_fx_pair(t)]))
        all_symbols = unique_tickers + [fx for fx in fx_pairs if fx]

        # 2. BATCH FETCH CURRENT PRICES (One single API call!)
        symbols_string = ','.join(all_symbols)
        quote_url = f"https://financialmodelingprep.com/api/v3/quote/{symbols_string}?apikey={API_KEY}"
        
        quote_response = requests.get(quote_url)
        quote_data = quote_response.json()
        
        # Tripwire for FMP errors
        if not quote_data or (isinstance(quote_data, dict) and 'Error Message' in quote_data):
            return jsonify({"error": "Failed to fetch data from FMP API. Check API Key.", "details": quote_data}), 500

        # Create a quick lookup dictionary for current prices
        current_prices = {item['symbol']: item['price'] for item in quote_data if 'symbol' in item and 'price' in item}

        holdings = []
        total_market_value = 0
        total_invested = 0
        
        # Aggregate net shares per ticker (handles buys and sells)
        portfolio_summary = df.groupby('ticker').agg(
            net_shares=('shares', 'sum'),
            first_buy=('purchase_date', 'min')
        ).reset_index()

        # 3. CALCULATE METRICS
        for _, row in portfolio_summary.iterrows():
            ticker = row['ticker']
            shares = row['net_shares']
            
            # Skip fully sold positions
            if shares <= 0: continue
            
            current_price_local = current_prices.get(ticker, 0.0)
            
            # Fetch historical purchase price 
            purchase_price_local = fetch_fmp_historical_price(ticker, row['first_buy'])
            if purchase_price_local is None:
                purchase_price_local = current_price_local # Fallback if history fails
                
            # Handle FX Conversion
            fx_pair = get_fx_pair(ticker)
            fx_rate = 1.0
            if fx_pair:
                fx_rate = current_prices.get(fx_pair, 1.0)
                
            current_price_usd = current_price_local * fx_rate
            purchase_price_usd = purchase_price_local * fx_rate
            
            # Math
            market_value = current_price_usd * shares
            invested_amount = purchase_price_usd * shares
            pnl = market_value - invested_amount
            return_pct = (pnl / invested_amount * 100) if invested_amount > 0 else 0
            
            total_market_value += market_value
            total_invested += invested_amount
            
            holdings.append({
                "ticker": ticker,
                "shares": int(shares),
                "purchase_price": round(purchase_price_usd, 2),
                "current_price": round(current_price_usd, 2),
                "market_value": round(market_value, 2),
                "profit_loss": round(pnl, 2),
                "return_pct": round(return_pct, 2)
            })

        # 4. FINAL PORTFOLIO MATH
        INITIAL_CAPITAL = 100000
        cash = INITIAL_CAPITAL - total_invested
        total_portfolio_value = total_market_value + cash
        total_return_pct = ((total_portfolio_value - INITIAL_CAPITAL) / INITIAL_CAPITAL) * 100
        total_pnl = total_portfolio_value - INITIAL_CAPITAL

        response = {
            "summary": {
                "initial_capital": INITIAL_CAPITAL,
                "current_value": round(total_portfolio_value, 2),
                "total_return_pct": round(total_return_pct, 2),
                "profit_loss": round(total_pnl, 2)
            },
            "holdings": sorted(holdings, key=lambda x: x['market_value'], reverse=True)
        }
        
        return jsonify(response)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# Vercel needs this to boot the WSGI application
if __name__ == '__main__':
    app.run(debug=True)