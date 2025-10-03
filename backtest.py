backtest.py :
import streamlit as st
import pandas as pd
import ccxt
from datetime import datetime, timedelta

@st.cache_data
def get_data(symbol, tf, start, end, warmup_bars=100):
    ex = ccxt.binance()
    start_dt = datetime.strptime(start, '%Y-%m-%d')
    
    if tf == '1h':
        warmup = timedelta(hours=warmup_bars)
    elif tf == '1m':
        warmup = timedelta(minutes=warmup_bars)
    else:
        warmup = timedelta(days=warmup_bars)
    
    since = int((start_dt - warmup).timestamp() * 1000)
    end_ms = int(datetime.strptime(end, '%Y-%m-%d').timestamp() * 1000)
    
    rows, cur = [], since
    while cur < end_ms:
        batch = ex.fetch_ohlcv(symbol, tf, cur, limit=1000)
        if not batch: break
        rows.extend(batch)
        cur = batch[-1][0] + 1
    
    df = pd.DataFrame(rows, columns=['ts','Open','High','Low','Close','Volume'])
    df['ts'] = pd.to_datetime(df['ts'], unit='ms', utc=True) + timedelta(hours=2)
    df.set_index('ts', inplace=True)
    return df

def backtest(df_exec, signals_1h, cap, tp, sl, fee, slip, tsl_on, tsl_arm, tsl_dist):
    cash, pos, trades = cap, None, []
    
    for i, (t, row) in enumerate(df_exec.iterrows()):
        o, h, l, c = row['Open'], row['High'], row['Low'], row['Close']
        hour = t.floor('H')
        
        if hour in signals_1h and pos is None:
            px = o * (1 + slip/100)
            pos = {'shares': cash/(px*(1+fee/100)), 'entry': px, 'time': t, 'high': h, 'tsl': False}
            cash = 0
        
        if pos:
            pos['high'] = max(pos['high'], h)
            tp_px = pos['entry'] * (1 + tp/100)
            sl_px = pos['entry'] * (1 - sl/100)
            tsl_px = None
            
            if tsl_on:
                gain = (pos['high']/pos['entry'] - 1) * 100
                if gain >= tsl_arm:
                    pos['tsl'] = True
                if pos['tsl']:
                    tsl_px = pos['entry'] * (1 + (gain - tsl_dist)/100)
            
            exit_px, reason = None, None
            if h >= tp_px:
                exit_px, reason = tp_px, 'TP'
            elif tsl_px and l <= tsl_px:
                exit_px, reason = tsl_px, 'TSL'
            elif l <= sl_px:
                exit_px, reason = sl_px, 'SL'
            
            if exit_px:
                exit_px *= (1 - slip/100)
                cash = pos['shares'] * exit_px * (1 - fee/100)
                ret = (exit_px/pos['entry'] - 1) * 100
                trades.append({'Entry': pos['time'], 'Exit': t, 'Return': ret, 'Reason': reason})
                pos = None
    
    return pd.DataFrame(trades)

st.set_page_config(page_title="Backtest Mobile", layout="wide")
st.title("Backtest EMA 6/40")

mode = st.sidebar.radio("Mode", ["Liste", "Custom"])

if mode == "Liste":
    coins = ["APT", "BTC", "ETH", "AVAX", "SOL", "DYDX", "ROSE", "BNB", "OP", "ARB"]
    base = st.sidebar.selectbox("Coin", coins)
    quote = st.sidebar.selectbox("Quote", ["USDC", "USDT"])
    symbol = f"{base}/{quote}"
else:
    symbol = st.sidebar.text_input("Paire", "APT/USDC").upper()

c1, c2 = st.sidebar.columns(2)
start = c1.date_input("Début", datetime(2025,9,1))
end = c2.date_input("Fin", datetime(2025,10,1))

cap = st.sidebar.number_input("Capital", 100, 1000000, 10000, 100)
tp = st.sidebar.number_input("TP %", 0.1, 20.0, 1.5, 0.1)
sl = st.sidebar.number_input("SL %", 0.1, 20.0, 3.5, 0.1)
fee = st.sidebar.number_input("Frais %", 0.0, 1.0, 0.10, 0.01)
slip = st.sidebar.number_input("Slippage %", 0.0, 1.0, 0.1, 0.01)

tsl = st.sidebar.checkbox("TSL", True)
tsl_arm = st.sidebar.number_input("TSL arm %", 0.0, 20.0, 2.0, 0.1) if tsl else 0
tsl_dist = st.sidebar.number_input("TSL dist %", 0.0, 20.0, 2.0, 0.1) if tsl else 0

if st.button("GO", type="primary"):
    try:
        with st.spinner(f"Chargement {symbol}..."):
            df_1h = get_data(symbol, '1h', str(start), str(end))
            df_1m = get_data(symbol, '1m', str(start), str(end), warmup_bars=200)
        
        ema6 = df_1h['Close'].ewm(span=6, adjust=False).mean()
        ema40 = df_1h['Close'].ewm(span=40, adjust=False).mean()
        cross = (ema6 > ema40) & (ema6.shift(1) <= ema40.shift(1))
        signals = set(df_1h.index[cross])
        
        st.info(f"Signaux: {len(signals)}")
        
        trades = backtest(df_1m, signals, cap, tp, sl, fee, slip, tsl, tsl_arm, tsl_dist)
        
        if len(trades) > 0:
            final = cap + trades['Return'].sum() * cap / 100
            wins = (trades['Return'] > 0).sum()
            
            c1, c2, c3 = st.columns(3)
            c1.metric("Return", f"{(final/cap-1)*100:.2f}%")
            c2.metric("Win Rate", f"{wins/len(trades)*100:.1f}%")
            c3.metric("Trades", len(trades))
            
            st.dataframe(trades, use_container_width=True)
        else:
            st.warning("Aucun trade")
    except Exception as e:
        st.error(f"Erreur: {e}")
