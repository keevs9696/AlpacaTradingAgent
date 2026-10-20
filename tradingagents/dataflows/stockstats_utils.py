import pandas as pd
from stockstats import wrap
from typing import Annotated
import os
from .config import get_config
from .alpaca_utils import AlpacaUtils
from .utils import safe_ticker_component


class StockstatsUtils:
    @staticmethod
    def get_stock_stats(
        symbol: Annotated[str, "ticker symbol for the company"],
        indicator: Annotated[
            str, "quantitative indicators based off of the stock data for the company"
        ],
        curr_date: Annotated[
            str, "curr date for retrieving stock price data, YYYY-mm-dd"
        ],
        data_dir: Annotated[
            str,
            "directory where the stock data is stored.",
        ],
        online: Annotated[
            bool,
            "whether to use online tools to fetch data or offline tools. If True, will use online tools.",
        ] = False,
    ):
        df = None
        data = None

        safe_symbol = safe_ticker_component(symbol)

        if not online:
            try:
                data = pd.read_csv(
                    os.path.join(
                        data_dir,
                        f"{safe_symbol}-Alpaca-data-2015-01-01-2025-03-25.csv",
                    ),
                    encoding="utf-8",
                )
                df = wrap(data)
            except FileNotFoundError:
                raise Exception("Stockstats fail: Alpaca data not fetched yet!")
        else:
            # Parse the current date
            curr_date_dt = pd.to_datetime(curr_date)

            # Get more historical data to ensure proper technical indicator calculations
            # Technical indicators like 50 SMA need at least 50+ days of data
            end_date = min(pd.Timestamp.today().normalize(), curr_date_dt.normalize())
            start_date = end_date - pd.DateOffset(days=365)  # Get 1 year of data for reliable indicators

            start_date_str = start_date.strftime("%Y-%m-%d")
            end_date_str = end_date.strftime("%Y-%m-%d")

            # Get config and ensure cache directory exists
            config = get_config()
            os.makedirs(config["data_cache_dir"], exist_ok=True)

            data_file = os.path.join(
                config["data_cache_dir"],
                f"{safe_symbol}-Alpaca-data-{start_date_str}-{end_date_str}.csv",
            )

            try:
                if os.path.exists(data_file):
                    # Import old CSVs into SQLite, retaining the CSV's age so
                    # recent bars are refreshed when the configured TTL expires.
                    try:
                        legacy_data = pd.read_csv(data_file, encoding="utf-8")
                    except Exception as csv_error:
                        return f"N/A: Malformed cached indicator data for {symbol}: {csv_error}"
                    required_raw_cols = {"Date", "Open", "High", "Low", "Close", "Volume"}
                    if not required_raw_cols.issubset(legacy_data.columns):
                        return f"N/A: Malformed cached indicator data for {symbol}: missing OHLCV columns"
                    AlpacaUtils.seed_stock_data_cache(
                        symbol,
                        legacy_data,
                        start_date_str,
                        end_date_str,
                        timeframe="1Day",
                        fetched_at=os.path.getmtime(data_file),
                    )

                # SQLite is the shared source of truth. It returns cached
                # history and only requests gaps or a stale recent tail.
                data = AlpacaUtils.get_stock_data(
                    symbol=symbol,
                    start_date=start_date_str,
                    end_date=end_date_str,
                    timeframe="1Day",
                )
                if data.empty:
                    return f"N/A: No data available for {symbol}"

                data = data.dropna(subset=[column for column in ("close", "Close") if column in data.columns])
                if "timestamp" in data.columns:
                    data = data.rename(
                        columns={
                            "timestamp": "Date",
                            "open": "Open",
                            "high": "High",
                            "low": "Low",
                            "close": "Close",
                            "volume": "Volume",
                        }
                    )

                # Keep lowercase aliases because Stockstats reads fields such
                # as close and volume while reports also use title case.
                required_cols_map = {
                    "Open": "open",
                    "High": "high",
                    "Low": "low",
                    "Close": "close",
                    "Volume": "volume",
                }
                for capitalized, lowercase in required_cols_map.items():
                    if capitalized in data.columns and lowercase not in data.columns:
                        data[lowercase] = data[capitalized]
                if "Date" in data.columns:
                    data["Date"] = pd.to_datetime(data["Date"])
                    data = data.sort_values("Date").drop_duplicates(subset=["Date"])
                data = data.reset_index(drop=True)
                data.to_csv(data_file, index=False, encoding="utf-8")

                # Ensure we have sufficient data for technical indicators
                if len(data) < 100:
                    return f"N/A: Insufficient data for {indicator} calculation (need at least 100 days, got {len(data)})"

                # Wrap with stockstats for technical indicator calculations
                df = wrap(data)

                # Trigger the indicator calculation
                # Handle problematic indicators that have issues with stockstats
                if indicator == 'obv':
                    try:
                        # Calculate OBV manually
                        obv_values = []
                        obv = 0
                        for i in range(len(data)):
                            if i == 0:
                                obv_values.append(0)
                            else:
                                if data['close'].iloc[i] > data['close'].iloc[i-1]:
                                    obv += data['volume'].iloc[i]
                                elif data['close'].iloc[i] < data['close'].iloc[i-1]:
                                    obv -= data['volume'].iloc[i]
                                # If close == prev close, OBV stays the same
                                obv_values.append(obv)

                        # Add OBV to the dataframe
                        df['obv'] = obv_values
                        indicator_series = df['obv']
                    except Exception as manual_error:
                        return f"N/A: Error calculating OBV manually: {str(manual_error)}"
                elif indicator == 'atr_14':
                    try:
                        # Calculate ATR manually
                        import numpy as np

                        # Calculate True Range
                        tr_values = []
                        for i in range(len(data)):
                            if i == 0:
                                tr_values.append(data['high'].iloc[i] - data['low'].iloc[i])
                            else:
                                tr1 = data['high'].iloc[i] - data['low'].iloc[i]
                                tr2 = abs(data['high'].iloc[i] - data['close'].iloc[i-1])
                                tr3 = abs(data['low'].iloc[i] - data['close'].iloc[i-1])
                                tr_values.append(max(tr1, tr2, tr3))

                        # Calculate 14-period ATR using simple moving average
                        atr_values = []
                        for i in range(len(tr_values)):
                            if i < 13:  # Not enough data for 14-period ATR
                                atr_values.append(np.nan)
                            else:
                                atr = np.mean(tr_values[i-13:i+1])
                                atr_values.append(atr)

                        # Add ATR to the dataframe
                        df['atr_14'] = atr_values
                        indicator_series = df['atr_14']
                    except Exception as manual_error:
                        return f"N/A: Error calculating ATR manually: {str(manual_error)}"
                elif indicator.endswith('_ema'):
                    try:
                        # Parse EMA indicator (e.g., 'close_8_ema')
                        parts = indicator.split('_')
                        column = parts[0]
                        window = int(parts[1])

                        # Calculate EMA manually
                        import numpy as np
                        alpha = 2.0 / (window + 1)
                        ema_values = []

                        for i in range(len(data)):
                            if i == 0:
                                ema_values.append(data[column].iloc[i])
                            else:
                                ema = alpha * data[column].iloc[i] + (1 - alpha) * ema_values[i-1]
                                ema_values.append(ema)

                        # Add EMA to the dataframe
                        df[indicator] = ema_values
                        indicator_series = df[indicator]
                    except Exception as manual_error:
                        return f"N/A: Error calculating EMA manually: {str(manual_error)}"
                elif indicator.endswith('_sma'):
                    try:
                        # Parse SMA indicator (e.g., 'close_50_sma')
                        parts = indicator.split('_')
                        column = parts[0]
                        window = int(parts[1])

                        # Calculate SMA manually
                        import numpy as np
                        sma_values = []

                        for i in range(len(data)):
                            if i < window - 1:
                                sma_values.append(np.nan)
                            else:
                                sma = np.mean(data[column].iloc[i-window+1:i+1])
                                sma_values.append(sma)

                        # Add SMA to the dataframe
                        df[indicator] = sma_values
                        indicator_series = df[indicator]
                    except Exception as manual_error:
                        return f"N/A: Error calculating SMA manually: {str(manual_error)}"
                else:
                    # Try stockstats for other indicators
                    try:
                        indicator_series = df[indicator]
                    except KeyError:
                        return f"N/A: Invalid indicator '{indicator}'"
                    except Exception as e:
                        return f"N/A: Error calculating {indicator}: {str(e)}"

                # Convert date column to string for matching
                df["date_str"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")
                curr_date_str = curr_date_dt.strftime("%Y-%m-%d")

                # Find the most recent trading day on or before the requested date
                available_dates = df["date_str"].tolist()
                matching_rows = df[df["date_str"] == curr_date_str]

                if not matching_rows.empty:
                    indicator_value = matching_rows[indicator].iloc[-1]  # Get the last (most recent) value
                    # Handle NaN values
                    if pd.isna(indicator_value):
                        return f"N/A: {indicator} not calculable for {curr_date_str}"
                    return float(indicator_value)
                else:
                    # If exact date not found, try to find the most recent trading day before the requested date
                    df_filtered = df[df["date_str"] <= curr_date_str]
                    if not df_filtered.empty:
                        most_recent = df_filtered.iloc[-1]
                        indicator_value = most_recent[indicator]
                        if pd.isna(indicator_value):
                            return f"N/A: {indicator} not calculable for most recent trading day"
                        actual_date = most_recent["date_str"]
                        return f"{float(indicator_value)} (as of {actual_date})"
                    else:
                        return f"N/A: No trading data available on or before {curr_date_str}"

            except Exception as e:
                return f"N/A: Error processing data for {symbol}: {str(e)}"
