"""
한국투자증권 API 래퍼 (미국 주식 스윙용)
"""
import json
import time
import requests
import pandas as pd
from pathlib import Path
from loguru import logger

from config.settings import KR_INVEST, IS_PAPER_TRADING

_TOKEN_CACHE_FILE = Path(__file__).parent.parent.parent / ".kr_invest_token.json"

KR_INVEST_HOST = (
    "https://openapivts.koreainvestment.com:29443"
    if IS_PAPER_TRADING
    else "https://openapi.koreainvestment.com:9443"
)


def log_exceptions(func):
    import functools
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception:
            logger.exception(f"Exception in {func.__qualname__}")
    return wrapper


class KRInvestAPI:
    def __init__(self):
        self.host = KR_INVEST_HOST
        self.account_num = KR_INVEST.get("account_num", "")
        self.token = self._login() or ""
        if not self.token:
            logger.warning("한국투자증권 API 연결 실패 - 미국 주식 기능 비활성화")

    def _load_cached_token(self) -> str:
        """파일 캐시에서 유효한 토큰 로드 (24시간 유효)"""
        try:
            if _TOKEN_CACHE_FILE.exists():
                data = json.loads(_TOKEN_CACHE_FILE.read_text(encoding="utf-8"))
                if data.get("expires_at", 0) > time.time() + 60:  # 1분 여유
                    return data.get("token", "")
        except Exception:
            pass
        return ""

    def _save_token_cache(self, token: str, expires_in: int = 86400):
        try:
            _TOKEN_CACHE_FILE.write_text(
                json.dumps({"token": token, "expires_at": time.time() + expires_in}),
                encoding="utf-8",
            )
        except Exception:
            pass

    @log_exceptions
    def _login(self) -> str:
        # 유효한 캐시 토큰이 있으면 재사용
        cached = self._load_cached_token()
        if cached:
            logger.info("한국투자증권 API 캐시 토큰 사용")
            return cached

        resp = requests.post(
            self.host + "/oauth2/tokenP",
            headers={"Content-Type": "application/json"},
            json={
                "grant_type": "client_credentials",
                "appkey": KR_INVEST["api_key"],
                "appsecret": KR_INVEST["api_secret_key"],
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        token = data.get("access_token", "")
        expires_in = data.get("expires_in", 86400)
        self._save_token_cache(token, expires_in)
        logger.info("한국투자증권 API 로그인 성공")
        return token

    def _headers(self, tr_id: str) -> dict:
        return {
            "Content-Type": "application/json",
            "authorization": f"Bearer {self.token}",
            "appkey": KR_INVEST["api_key"],
            "appsecret": KR_INVEST["api_secret_key"],
            "tr_id": tr_id,
            "custtype": "P",
        }

    # ── 미국 주식 현재가 조회 ─────────────────────────────
    @log_exceptions
    def get_us_stock_price(self, ticker: str, exchange: str = "NAS") -> dict | None:
        """
        exchange: NAS(나스닥), NYS(NYSE), AMS(AMEX)
        """
        resp = requests.get(
            self.host + "/uapi/overseas-price/v1/quotations/price",
            headers=self._headers("HHDFS00000300"),
            params={"AUTH": "", "EXCD": exchange, "SYMB": ticker},
            timeout=10,
        )
        resp.raise_for_status()
        out = resp.json().get("output", {})
        if not out:
            return None
        return {
            "ticker": ticker,
            "현재가": float(out.get("last", 0)),
            "등락률": float(out.get("rate", 0)),
            "거래량": int(out.get("tvol", 0)),
        }

    # ── 미국 주식 일봉 차트 ───────────────────────────────
    @log_exceptions
    def get_us_daily_chart(self, ticker: str, exchange: str = "NAS", count: int = 60) -> pd.DataFrame:
        resp = requests.get(
            self.host + "/uapi/overseas-price/v1/quotations/dailyprice",
            headers=self._headers("HHDFS76240000"),
            params={
                "AUTH": "", "EXCD": exchange, "SYMB": ticker,
                "GUBN": "0",  # 0:일, 1:주, 2:월
                "BYMD": "", "MODP": "0", "COUNT": str(count),
            },
            timeout=10,
        )
        resp.raise_for_status()
        output2 = resp.json().get("output2", [])
        if not output2:
            return pd.DataFrame()
        df = pd.DataFrame(output2)
        df = df[::-1].reset_index(drop=True)
        rename_map = {
            "xymd": "Date", "open": "Open", "high": "High",
            "low": "Low", "clos": "Close", "tvol": "Volume",
        }
        df.rename(columns=rename_map, inplace=True)
        for col in ["Open", "High", "Low", "Close"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "Volume" in df.columns:
            df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce").fillna(0).astype(int)
        return df[["Date", "Open", "High", "Low", "Close", "Volume"]]

    # ── 미국 주식 매수 주문 ───────────────────────────────
    @log_exceptions
    def buy_us_stock(self, ticker: str, qty: int, exchange: str = "NAS") -> dict | None:
        tr_id = "VTTT1002U" if IS_PAPER_TRADING else "TTTT1002U"
        resp = requests.post(
            self.host + "/uapi/overseas-stock/v1/trading/order",
            headers=self._headers(tr_id),
            json={
                "CANO": self.account_num[:8],
                "ACNT_PRDT_CD": self.account_num[8:] if len(self.account_num) > 8 else "01",
                "OVRS_EXCG_CD": exchange,
                "PDNO": ticker,
                "ORD_DVSN": "00",   # 00: 지정가, 32: 시장가
                "ORD_QTY": str(qty),
                "OVRS_ORD_UNPR": "0",  # 시장가
                "ORD_SVR_DVSN_CD": "0",
            },
            timeout=10,
        )
        resp.raise_for_status()
        logger.info(f"[미국 매수] {ticker} {qty}주 | 결과: {resp.json()}")
        return resp.json()

    # ── 미국 주식 매도 주문 ───────────────────────────────
    @log_exceptions
    def sell_us_stock(self, ticker: str, qty: int, exchange: str = "NAS") -> dict | None:
        tr_id = "VTTT1001U" if IS_PAPER_TRADING else "TTTT1006U"
        resp = requests.post(
            self.host + "/uapi/overseas-stock/v1/trading/order",
            headers=self._headers(tr_id),
            json={
                "CANO": self.account_num[:8],
                "ACNT_PRDT_CD": self.account_num[8:] if len(self.account_num) > 8 else "01",
                "OVRS_EXCG_CD": exchange,
                "PDNO": ticker,
                "ORD_DVSN": "00",
                "ORD_QTY": str(qty),
                "OVRS_ORD_UNPR": "0",
                "ORD_SVR_DVSN_CD": "0",
            },
            timeout=10,
        )
        resp.raise_for_status()
        logger.info(f"[미국 매도] {ticker} {qty}주 | 결과: {resp.json()}")
        return resp.json()
