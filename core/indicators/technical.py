"""
기술적 지표 계산 모듈
pandas_ta 기반 (StockDataAnalysis 프로젝트 활용)
"""
import pandas as pd

try:
    import pandas_ta as ta
    PANDAS_TA_AVAILABLE = True
except ImportError:
    PANDAS_TA_AVAILABLE = False

from config.settings import INDICATORS


class TechnicalIndicators:
    def __init__(self, mode: str = "daytrading"):
        """mode: 'daytrading' | 'swing'"""
        self.params = INDICATORS[mode]

    def add_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """OHLCV DataFrame에 모든 지표 추가"""
        df = df.copy()
        df = self.add_rsi(df)
        df = self.add_macd(df)
        df = self.add_bollinger_bands(df)
        return df

    def add_rsi(self, df: pd.DataFrame) -> pd.DataFrame:
        period = self.params["rsi_period"]
        if PANDAS_TA_AVAILABLE:
            df[f"RSI_{period}"] = ta.rsi(df["Close"], length=period)
        else:
            delta = df["Close"].diff()
            gain = delta.clip(lower=0).rolling(period).mean()
            loss = (-delta.clip(upper=0)).rolling(period).mean()
            rs = gain / loss.replace(0, float("nan"))
            df[f"RSI_{period}"] = 100 - (100 / (1 + rs))
        return df

    def add_macd(self, df: pd.DataFrame) -> pd.DataFrame:
        fast = self.params["macd_fast"]
        slow = self.params["macd_slow"]
        signal = self.params["macd_signal"]
        if PANDAS_TA_AVAILABLE:
            macd = ta.macd(df["Close"], fast=fast, slow=slow, signal=signal)
            if macd is not None:
                df["MACD"] = macd[f"MACD_{fast}_{slow}_{signal}"]
                df["MACD_signal"] = macd[f"MACDs_{fast}_{slow}_{signal}"]
                df["MACD_hist"] = macd[f"MACDh_{fast}_{slow}_{signal}"]
        else:
            ema_fast = df["Close"].ewm(span=fast, adjust=False).mean()
            ema_slow = df["Close"].ewm(span=slow, adjust=False).mean()
            df["MACD"] = ema_fast - ema_slow
            df["MACD_signal"] = df["MACD"].ewm(span=signal, adjust=False).mean()
            df["MACD_hist"] = df["MACD"] - df["MACD_signal"]
        return df

    def add_bollinger_bands(self, df: pd.DataFrame) -> pd.DataFrame:
        period = self.params["bb_period"]
        std = self.params["bb_std"]
        if PANDAS_TA_AVAILABLE:
            bb = ta.bbands(df["Close"], length=period, std=std)
            if bb is not None:
                # pandas_ta column format: BBU_{period}_{std}_{std}
                std_f = float(std)
                prefix = f"{period}_{std_f}"
                bb_upper_col = next((c for c in bb.columns if c.startswith(f"BBU_{prefix}")), None)
                bb_mid_col = next((c for c in bb.columns if c.startswith(f"BBM_{prefix}")), None)
                bb_lower_col = next((c for c in bb.columns if c.startswith(f"BBL_{prefix}")), None)
                if bb_upper_col:
                    df["BB_upper"] = bb[bb_upper_col]
                    df["BB_mid"] = bb[bb_mid_col]
                    df["BB_lower"] = bb[bb_lower_col]
        else:
            mid = df["Close"].rolling(period).mean()
            sigma = df["Close"].rolling(period).std()
            df["BB_upper"] = mid + std * sigma
            df["BB_mid"] = mid
            df["BB_lower"] = mid - std * sigma
        return df

    def get_signal(self, df: pd.DataFrame) -> str:
        """
        마지막 봉 기준 매매 신호 반환
        반환: 'BUY' | 'SELL' | 'HOLD'
        """
        if df.empty or len(df) < 2:
            return "HOLD"

        last = df.iloc[-1]
        rsi_col = f"RSI_{self.params['rsi_period']}"

        buy_signals = 0
        sell_signals = 0

        # RSI
        if rsi_col in df.columns and pd.notna(last.get(rsi_col)):
            if last[rsi_col] < self.params["rsi_oversold"]:
                buy_signals += 1
            elif last[rsi_col] > self.params["rsi_overbought"]:
                sell_signals += 1

        # MACD
        if "MACD_hist" in df.columns and pd.notna(last.get("MACD_hist")):
            prev = df.iloc[-2]
            if prev["MACD_hist"] < 0 and last["MACD_hist"] > 0:
                buy_signals += 1
            elif prev["MACD_hist"] > 0 and last["MACD_hist"] < 0:
                sell_signals += 1

        # 볼린저밴드
        if "BB_lower" in df.columns and pd.notna(last.get("BB_lower")):
            if last["Close"] <= last["BB_lower"]:
                buy_signals += 1
            elif last["Close"] >= last["BB_upper"]:
                sell_signals += 1

        if buy_signals >= 2:
            return "BUY"
        elif sell_signals >= 2:
            return "SELL"
        return "HOLD"
