# Nifty 500 Institutional CMF Breakout Screener

## Files
- `app.py` — Streamlit screener.
- `requirements.txt` — Python dependencies.
- `nifty500_stocks.csv` — seed CSV; the app fills it with the official constituents on the first successful download.
- `README.md` — deployment instructions.

## Deploy
1. Extract this ZIP.
2. Upload all four files to the root of your GitHub repository.
3. In Streamlit Community Cloud, select the repository and set Main file path to `app.py`.
4. Deploy.

## Saved constituent list
- First scan: if the CSV is empty, the app downloads the official Nifty 500 constituents and saves the result in `nifty500_stocks.csv`.
- Later scans: it reads the saved CSV and does not repeatedly download the constituent list.
- To update membership, click **Refresh Nifty 500 List** in the sidebar.
- Note: Streamlit Community Cloud's runtime filesystem is not guaranteed to persist across rebuilds/restarts. For permanent version control, download/commit the populated CSV into GitHub after it is generated.

## Screening logic
- Trend: latest Close > selected EMA (default 50).
- CMF: selected period (default 20) > 0.05.
- Breakout: latest Close > highest High of the previous selected sessions; current candle excluded.
- Volume surge: latest volume > selected multiple (default 1.5x) of prior 20-session average; current candle excluded from average.
- Confirmed: all four conditions pass.
- Near breakout: trend + CMF + volume pass, while resistance has not yet been crossed.

## Limitations
Yahoo Finance data can be delayed, incomplete, throttled, or unavailable. During market hours, current daily volume is partial, so volume signals are provisional. This is a screening tool, not a trade recommendation.
