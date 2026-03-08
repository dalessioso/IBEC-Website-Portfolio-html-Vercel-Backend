from flask import Flask, jsonify
from flask_cors import CORS
import pandas as pd
import os
import requests

app = Flask(__name__)
CORS(app)

API_KEY = "nljARgm0v27ktpQ3x7jIFBcZJmUJW3sz"

def get_fx_pair(ticker):
    if '.NS' in ticker: return 'INRUSD'
    if '.MC' in ticker: return 'EURUSD'
    return None

def clean_ticker_for_fmp(ticker):
    # FMP Stable sometimes struggles with dots. 
    # If the quote fails, we might need to swap .NS to :NSE, 
    # but let's try standardizing to uppercase first.
    return ticker.upper().strip()

@app.route('/api', methods=['GET'])
def get_portfolio():
    try:
        csv_path = os.path.join(os.path.dirname(__file__), '..', 'trades.csv')
        if not os.path.exists(csv_path):
            return jsonify({"error": "trades.csv missing"}), 404
            
        df = pd.read_csv(csv_path)
        df.columns = ['ticker', 'shares', 'purchase_date']
        
        unique_tickers = [clean_ticker_for_fmp(t) for t in df['ticker'].unique()]
        fx_pairs = [get_fx_pair(t) for t in unique_tickers if get_fx_pair(t)]
        all_symbols = list(set(unique_tickers + fx_pairs))

        # --- THE FIX: Better Request Handling ---
        symbols_string = ','.join(all_symbols)
        quote_url = f"https://financialmodelingprep.com/api/v3/quote/{symbols_string}?apikey={API_KEY}"
        
        response = requests.get(quote_url)
        
        # Check if the server actually returned a 200 OK
        if response.status_code != 200:
            return jsonify({
                "error": f"FMP Server returned status {response.status_code}",
                "raw_text": response.text[:200]
            }), 500

        quote_data = response.json()

        # If FMP returns a list, it's a success. If a dict with Error Message, it's a failure.
        if isinstance(quote_data, dict) and "Error Message" in quote_data:
            # If v3 fails, let's try the stable fallback automatically
            stable_url = f"https://financialmodelingprep.com/stable/batch-quote?symbol={symbols_string}&apikey={API_KEY}"
            quote_data = requests.get(stable_url).json()

        current_prices = {item['symbol']: item['price'] for item in quote_data if 'symbol' in item}

        holdings = []
        total_market_value = 0
        total_invested = 0
        
        summary_df = df.groupby('ticker')['shares'].sum().reset_index()

        for _, row in summary_df.iterrows():
            ticker = row['ticker']
            shares = row['shares']
            if shares <= 0: continue
            
            # Use current price as a placeholder for purchase price to stop the crashes
            # until you add purchase_price to your CSV
            price = current_prices.get(ticker, 0)
            
            fx_pair = get_fx_pair(ticker)
            fx_rate = current_prices.get(fx_pair, 1.0) if fx_pair else 1.0
            
            usd_price = price * fx_rate
            mkt_val = usd_price * shares
            
            total_market_value += mkt_val
            total_invested += mkt_val # Temporary placeholder
            
            holdings.append({
                "ticker": ticker,
                "shares": int(shares),
                "current_price": round(usd_price, 2),
                "market_value": round(mkt_val, 2)
            })

        return jsonify({
            "summary": {
                "total_value": round(total_market_value, 2),
                "holdings_count": len(holdings)
            },
            "holdings": holdings
        })
        
    except Exception as e:
        return jsonify({"error": str(e), "type": str(type(e))}), 500

if __name__ == '__main__':
    app.run(debug=True)