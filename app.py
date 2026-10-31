import io
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import streamlit as st
import yfinance as yf


st.set_page_config(
    page_title="Nifty 500 CMF Breakout Screener",
    page_icon="📈",
    layout="wide",
)

st.title("📈 Institutional CMF Breakout Screener — Nifty 500")
st.markdown(
    "Scans Nifty 500 stocks for **EMA trend + Chaikin Money Flow (CMF) "
    "+ price breakout + volume surge**. The latest daily candle is included; "
    "signals during market hours are provisional."
)

CONSTITUENT_URLS = [
    "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
    "https://niftyindices.com/IndexConstituent/ind_nifty500list.csv",
]


CONSTITUENT_FILE = "nifty500_stocks.csv"


def load_nifty500(force_refresh=False):
    """Read local constituents first; download only if missing or manually refreshed."""
    if not force_refresh and os.path.exists(CONSTITUENT_FILE):
        try:
            saved = pd.read_csv(CONSTITUENT_FILE)
            symbol_col = next(
                (c for c in saved.columns if str(c).strip().upper() == "SYMBOL"),
                None,
            )
            if symbol_col is None:
                symbol_col = next(
                    (c for c in saved.columns if str(c).strip().upper() == "SYMBOLS"),
                    None,
                )
            if symbol_col is not None:
                symbols = (
                    saved[symbol_col].astype(str).str.strip().str.upper()
                    .replace("", np.nan).dropna().drop_duplicates().tolist()
                )
                symbols = [s for s in symbols if s not in {"NAN", "SYMBOL"}]
                if len(symbols) >= 450:
                    return [s if s.endswith(".NS") else f"{s}.NS" for s in symbols], None
        except Exception:
            pass

    errors = []
    headers = {"User-Agent": "Mozilla/5.0"}
    for url in CONSTITUENT_URLS:
        try:
            response = requests.get(url, headers=headers, timeout=25)
            response.raise_for_status()
            downloaded = pd.read_csv(io.BytesIO(response.content))
            cols = {str(c).strip().upper(): c for c in downloaded.columns}
            symbol_col = cols.get("SYMBOL")
            if symbol_col is None or downloaded.empty:
                errors.append(f"Unexpected CSV format from {url}")
                continue

            symbols = (
                downloaded[symbol_col].astype(str).str.strip().str.upper()
                .replace("", np.nan).dropna().drop_duplicates().tolist()
            )
            symbols = [s for s in symbols if s not in {"NAN", "SYMBOL"}]
            if len(symbols) >= 450:
                downloaded.to_csv(CONSTITUENT_FILE, index=False)
                return [f"{s}.NS" for s in symbols], None
            errors.append(f"Only {len(symbols)} symbols received from {url}")
        except Exception as exc:
            errors.append(f"{url}: {exc}")

    return [], (
        "Could not load a valid saved Nifty 500 list or download the official CSV. "
        + " | ".join(errors)
    )

with st.sidebar:
    st.header("⚙️ Screener Settings")
    ema_period = st.number_input(
        "EMA period", min_value=10, max_value=200, value=50, step=5
    )
    cmf_period = st.number_input(
        "CMF period", min_value=5, max_value=50, value=20
    )
    breakout_period = st.number_input(
        "Resistance lookback (sessions)",
        min_value=5,
        max_value=100,
        value=20,
    )
    volume_multiplier = st.number_input(
        "Volume surge multiplier",
        min_value=1.0,
        max_value=5.0,
        value=1.5,
        step=0.1,
    )
    batch_size = st.selectbox(
        "Download batch size",
        [10, 20, 25, 40, 50],
        index=2,
        help="Use smaller batches if Yahoo Finance throttles requests.",
    )
    run_button = st.button(
        "🚀 Scan Nifty 500", type="primary", use_container_width=True
    )
    refresh_button = st.button(
        "🔄 Refresh Nifty 500 List", use_container_width=True
    )

if refresh_button:
    with st.spinner("Downloading the official Nifty 500 list…"):
        refreshed_symbols, refresh_error = load_nifty500(force_refresh=True)
    if refresh_error:
        st.error(refresh_error)
    else:
        st.success(
            f"Saved {len(refreshed_symbols)} constituents in "
            f"{CONSTITUENT_FILE}. Future scans will read the local CSV."
        )

st.caption(
    "Constituents: local CSV after first download; use Refresh to update. "
    "Market data may be delayed, incomplete, or unavailable for some symbols."
)
st.warning(
    "Intraday caution: Yahoo Finance daily volume for the current session may be "
    "partial, while the comparison average uses completed prior sessions. "
    "Volume-based signals can therefore change materially before market close."
)


def extract_ticker_frame(download_data, symbol):
    """Handle common yfinance MultiIndex layouts and single-ticker results."""
    if download_data is None or download_data.empty:
        return None

    if not isinstance(download_data.columns, pd.MultiIndex):
        return download_data.copy()

    # group_by='ticker' normally puts ticker at level 0.
    level0 = download_data.columns.get_level_values(0)
    if symbol in level0:
        return download_data[symbol].copy()

    # Be tolerant of the alternate field-first layout.
    level1 = download_data.columns.get_level_values(1)
    if symbol in level1:
        return download_data.xs(symbol, axis=1, level=1).copy()

    return None


def compute_row(symbol, raw):
    if raw is None or raw.empty:
        return None

    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        # A per-ticker slice should be flat; reject unexpected ambiguity safely.
        df.columns = df.columns.get_level_values(-1)

    required = ["High", "Low", "Close", "Volume"]
    if not all(column in df.columns for column in required):
        return None

    df = df[required].apply(pd.to_numeric, errors="coerce").dropna()
    df = df[~df.index.duplicated(keep="last")].sort_index()

    required_history = max(ema_period, cmf_period, breakout_period, 20) + 2
    if len(df) < required_history:
        return None

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]

    ema = close.ewm(span=ema_period, adjust=False, min_periods=ema_period).mean()

    spread = high - low
    money_flow_multiplier = (
        ((close - low) - (high - close))
        .div(spread.replace(0, np.nan))
        .fillna(0.0)
    )
    money_flow_volume = money_flow_multiplier * volume
    volume_sum = volume.rolling(cmf_period, min_periods=cmf_period).sum()
    cmf = (
        money_flow_volume.rolling(cmf_period, min_periods=cmf_period)
        .sum()
        .div(volume_sum.replace(0, np.nan))
    )

    # Exclude the current candle from both reference calculations.
    resistance = high.shift(1).rolling(
        breakout_period, min_periods=breakout_period
    ).max()
    average_volume = volume.shift(1).rolling(20, min_periods=20).mean()

    latest = df.index[-1]
    price = float(close.iloc[-1])
    ema_value = float(ema.iloc[-1])
    cmf_value = float(cmf.iloc[-1])
    resistance_value = float(resistance.iloc[-1])
    current_volume = float(volume.iloc[-1])
    avg_volume = float(average_volume.iloc[-1])

    values = [
        price,
        ema_value,
        cmf_value,
        resistance_value,
        current_volume,
        avg_volume,
    ]
    if not np.isfinite(values).all() or avg_volume <= 0:
        return None

    trend_ok = price > ema_value
    cmf_ok = cmf_value > 0.05
    breakout_ok = price > resistance_value
    volume_ok = current_volume > volume_multiplier * avg_volume

    confirmed = trend_ok and cmf_ok and breakout_ok and volume_ok
    near_breakout = trend_ok and cmf_ok and volume_ok and not breakout_ok

    if confirmed:
        signal = "🚀 Breakout Confirmed"
    elif near_breakout:
        signal = "👀 Near Breakout"
    else:
        signal = "⏳ Wait / Watch"

    return {
        "Ticker": symbol,
        "Candle date": pd.Timestamp(latest).strftime("%Y-%m-%d"),
        "CMP (₹)": round(price, 2),
        f"EMA {ema_period}": round(ema_value, 2),
        f"CMF ({cmf_period})": round(cmf_value, 3),
        f"{breakout_period}D Resistance (₹)": round(resistance_value, 2),
        "Volume": int(current_volume),
        "Prev 20D Avg Volume": int(avg_volume),
        "Trend": "✅" if trend_ok else "❌",
        "CMF > 0.05": "✅" if cmf_ok else "❌",
        "Breakout": "✅" if breakout_ok else "❌",
        "Volume Surge": "✅" if volume_ok else "❌",
        "Signal": signal,
    }


if run_button:
    symbols, error = load_nifty500()

    if error:
        st.error(error)
        st.info(
            "Please retry later. The app will not silently replace the Nifty 500 "
            "universe with a smaller watchlist."
        )
        st.stop()

    st.info(
        f"Loaded {len(symbols)} constituents from the saved local CSV. "
        "Downloading two years of daily history in batches…"
    )
    progress = st.progress(0.0)
    status = st.empty()
    rows = []
    failed = []
    total_batches = (len(symbols) + batch_size - 1) // batch_size

    for batch_no, start in enumerate(
        range(0, len(symbols), batch_size), start=1
    ):
        batch = symbols[start : start + batch_size]
        status.text(
            f"Fetching batch {batch_no}/{total_batches}: "
            f"{batch[0]} … {batch[-1]}"
        )

        try:
            data = yf.download(
                tickers=batch,
                period="2y",
                interval="1d",
                auto_adjust=True,
                group_by="ticker",
                progress=False,
                threads=True,
                timeout=30,
            )

            for symbol in batch:
                try:
                    ticker_data = extract_ticker_frame(data, symbol)
                    result = compute_row(symbol, ticker_data)
                    if result is not None:
                        rows.append(result)
                    else:
                        failed.append(symbol)
                except Exception:
                    failed.append(symbol)

        except Exception:
            failed.extend(batch)

        progress.progress(min(batch_no / total_batches, 1.0))
        time.sleep(0.35)

    progress.empty()
    status.empty()

    if not rows:
        st.error(
            "No usable stock data returned. Yahoo Finance may be throttling "
            "requests; retry later or reduce the download batch size."
        )
        if failed:
            st.caption(f"Unavailable/skipped symbols: {len(set(failed))}")
        st.stop()

    result_df = pd.DataFrame(rows)
    confirmed = result_df[
        result_df["Signal"] == "🚀 Breakout Confirmed"
    ].copy()
    near = result_df[
        result_df["Signal"] == "👀 Near Breakout"
    ].copy()
    scanned_count = len(result_df)

    metrics = st.columns(4)
    metrics[0].metric("Nifty 500 constituents", len(symbols))
    metrics[1].metric("Stocks with usable data", scanned_count)
    metrics[2].metric("Confirmed breakouts", len(confirmed))
    metrics[3].metric("Near breakout", len(near))

    signal_order = {
        "🚀 Breakout Confirmed": 0,
        "👀 Near Breakout": 1,
        "⏳ Wait / Watch": 2,
    }
    result_df["_order"] = result_df["Signal"].map(signal_order)
    result_df = (
        result_df.sort_values(
            ["_order", f"CMF ({cmf_period})"],
            ascending=[True, False],
        )
        .drop(columns="_order")
    )

    # Sort the filtered tabs using the same ranking as the full results.
    confirmed = result_df[
        result_df["Signal"] == "🚀 Breakout Confirmed"
    ]
    near = result_df[
        result_df["Signal"] == "👀 Near Breakout"
    ]

    tab_all, tab_confirmed, tab_near = st.tabs(
        ["All scanned stocks", "Confirmed breakout", "Near breakout"]
    )
    with tab_all:
        st.dataframe(result_df, use_container_width=True, hide_index=True)
    with tab_confirmed:
        st.dataframe(confirmed, use_container_width=True, hide_index=True)
    with tab_near:
        st.dataframe(near, use_container_width=True, hide_index=True)

    st.download_button(
        "📥 Download full scan (CSV)",
        data=result_df.to_csv(index=False).encode("utf-8-sig"),
        file_name=(
            "Nifty500_CMF_Screener_"
            f"{datetime.now(ZoneInfo('Asia/Kolkata')).strftime('%Y%m%d_%H%M')}.csv"
        ),
        mime="text/csv",
    )

    st.caption(
        f"Data returned for {scanned_count}/{len(symbols)} constituents. "
        f"Unavailable/skipped: {len(set(failed))}. "
        "Intraday values can change until market close."
    )
