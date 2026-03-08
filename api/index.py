from flask import Flask, jsonify
from flask_cors import CORS
import yfinance as yf
import pandas as pd
import os
import requests

# Reroute yfinance cache to Vercel's writable /tmp directory
yf.set_tz_cache_location("/tmp/yfinance")

app = Flask(__name__)
CORS(app)

def get_fx_pair(ticker):
    if ticker.endswith('.NS'): return 'INRUSD=X'
    if ticker.endswith('.MC'): return 'EURUSD=X'
    if ticker.endswith('.L'): return 'GBPUSD=X'
    return None

@app.route('/api', methods=['GET'])
def get_portfolio():
    try:
        csv_path = os.path.join(os.path.dirname(__file__), '..', 'trades.csv')
        
        # TRIPWIRE 1: Check if Vercel actually bundled the CSV file
        if not os.path.exists(csv_path):
            return jsonify({"error": f"CRITICAL: trades.csv not found at {csv_path}. Check vercel.json includeFiles."}), 404
            
        df = pd.read_csv(csv_path)
        
        # TRIPWIRE 2: Check if the CSV is being read but is completely empty
        if df.empty:
            return jsonify({"error": "CRITICAL: trades.csv was found and read, but it contains no data!"}), 400
        
        df.columns = ['ticker', 'shares', 'purchase_date']
        df['purchase_date'] = pd.to_datetime(df['purchase_date'])
        
        today = pd.Timestamp.today().normalize()
        df = df[df['purchase_date'] <= today]
        
        unique_tickers = df['ticker'].unique().tolist()
        fx_pairs = list(set([get_fx_pair(t) for t in unique_tickers if get_fx_pair(t)]))
        all_symbols = unique_tickers + fx_pairs

        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        })

        data = yf.download(
            all_symbols, 
            period="2y", 
            group_by='ticker', 
            threads=False,    
            session=session   
        )
        
        # TRIPWIRE 3: Check if Yahoo Finance blocked the Vercel server IP
        if data is None or data.empty:
            return jsonify({
                "error": "CRITICAL: Yahoo Finance returned an empty dataset. The Vercel AWS IP is blocked.",
                "symbols_requested": all_symbols,
                "action_required": "Swap yfinance for a free API like Alpha Vantage or Finnhub."
            }), 403
        
        holdings = []
        total_market_value = 0
        total_invested = 0
        
        portfolio_summary = df.groupby('ticker').agg(
            net_shares=('shares', 'sum'),
            first_buy=('purchase_date', 'min')
        ).reset_index()

        for _, row in portfolio_summary.iterrows():
            ticker = row['ticker']
            shares = row['net_shares']
            
            if shares <= 0: continue
            
            if len(all_symbols) == 1:
                hist = data
            else:
                if ticker in data.columns.levels[0]:
                    hist = data[ticker]
                elif ticker in data.columns.levels[1]:
                    hist = data.xs(ticker, level=1, axis=1)
                else:
                    hist = None
                
            if hist is None or hist.empty: continue
            
            current_price_local = float(hist['Close'].iloc[-1])
            
            buy_date = row['first_buy']
            try:
                idx = hist.index.get_indexer([buy_date], method='bfill')[0]
                purchase_price_local = float(hist['Close'].iloc[idx])
            except:
                purchase_price_local = current_price_local 
                
            fx_pair = get_fx_pair(ticker)
            fx_rate = 1.0
            if fx_pair:
                if fx_pair in data.columns.levels[0]:
                    fx_hist = data[fx_pair]
                    fx_rate = float(fx_hist['Close'].iloc[-1])
                elif fx_pair in data.columns.levels[1]:
                    fx_hist = data.xs(fx_pair, level=1, axis=1)
                    fx_rate = float(fx_hist['Close'].iloc[-1])
                
            current_price_usd = current_price_local * fx_rate
            purchase_price_usd = purchase_price_local * fx_rate
            
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

if __name__ == '__main__':
    app.run(debug=True)