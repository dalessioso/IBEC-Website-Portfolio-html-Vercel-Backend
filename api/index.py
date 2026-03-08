from flask import Flask, jsonify
from flask_cors import CORS
import pandas as pd
import os
import requests
import time

app = Flask(__name__)
CORS(app)

# Your Alpha Vantage Key
AV_API_KEY = "0JUBXOSI8DKOU8ZV"

def get_av_price(ticker):
    """Fetches global quote from Alpha Vantage with error handling."""
    # Alpha Vantage uses 'NSE:TMCV' or 'TMCV.NSE' for India. 
    # We will try to clean the ticker format here.
    clean_ticker = ticker.replace('.NS', '.NSE').replace('.MC', '.MAD')
    
    url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={clean_ticker}&apikey={AV_API_KEY}"
    try:
        response = requests.get(url)
        data = response.json()
        
        # Check if we hit the limit
        if "Note" in data:
            print(f"RATE LIMIT HIT: {data['Note']}")
            return -1
            
        quote = data.get("Global Quote", {})
        price = quote.get("05. price", 0)
        return float(price)
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return 0

@app.route('/api', methods=['GET'])
def get_portfolio():
    try:
        csv_path = os.path.join(os.path.dirname(__file__), '..', 'trades.csv')
        df = pd.read_csv(csv_path)
        df.columns = ['ticker', 'shares', 'purchase_date']
        
        summary_df = df.groupby('ticker')['shares'].sum().reset_index()
        holdings = []
        total_market_value_usd = 0
        
        for i, row in summary_df.iterrows():
            ticker = row['ticker']
            shares = row['shares']
            
            if shares <= 0: continue
            
            # THE LOCK: Stay under 5 requests per minute (1 request every 12.5 seconds)
            if i > 0:
                time.sleep(12.5)
            
            price_local = get_av_price(ticker)
            
            # If price_local is -1, it means we hit the daily 25-request cap
            if price_local == -1:
                return jsonify({"error": "Alpha Vantage Daily Limit (25 calls) reached. Try again tomorrow or upgrade."}), 429

            # Simple Currency Multipliers
            multiplier = 1.0
            if '.NS' in ticker: multiplier = 0.012  # INR to USD
            if '.MC' in ticker: multiplier = 1.08   # EUR to USD
            
            price_usd = price_local * multiplier
            mkt_val = price_usd * shares
            total_market_value_usd += mkt_val
            
            holdings.append({
                "ticker": ticker,
                "shares": int(shares),
                "current_price": round(price_usd, 2),
                "market_value": round(mkt_val, 2)
            })

        return jsonify({
            "summary": {
                "total_value": round(total_market_value_usd, 2),
                "api": "Alpha Vantage Free",
                "calls_used": len(holdings)
            },
            "holdings": holdings
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)