"""
키움증권 REST API 래퍼
KiwoomREST/chapter10/utils.py 기반으로 Antikythera에 맞게 정리
"""
import time
import requests
import pandas as pd
from loguru import logger

from config.settings import KIWOOM, IS_PAPER_TRADING


KIWOOM_HOST = "https://mockapi.kiwoom.com" if IS_PAPER_TRADING else "https://api.kiwoom.com"
KIWOOM_WS_URL = (
    "wss://mockapi.kiwoom.com:10000/api/dostk/websocket"
    if IS_PAPER_TRADING
    else "wss://api.kiwoom.com:10000/api/dostk/websocket"
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


class KiwoomAPI:
    def __init__(self):
        self.host = KIWOOM_HOST
        self.ws_url = KIWOOM_WS_URL
        self.account_num = KIWOOM.get("account_num", "")
        self.token = self._login()

    def _make_headers(self, api_id: str, cont_yn: str = "N", next_key: str = "") -> dict:
        return {
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {self.token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": api_id,
        }

    @log_exceptions
    def _login(self) -> str:
        params = {
            "grant_type": "client_credentials",
            "appkey": KIWOOM["api_key"],
            "secretkey": KIWOOM["api_secret_key"],
        }
        response = requests.post(
            self.host + "/oauth2/token",
            headers={"Content-Type": "application/json;charset=UTF-8"},
            json=params,
        )
        response.raise_for_status()
        logger.info("키움 API 로그인 성공")
        return response.json()["token"]

    # ── 현재가 조회 (ka10007) ─────────────────────────────
    @log_exceptions
    def get_stock_price(self, stock_code: str) -> dict:
        data = {"stk_cd": stock_code}
        response = requests.post(
            self.host + "/api/dostk/mrkcond",
            headers=self._make_headers("ka10007"),
            json=data,
        )
        response.raise_for_status()
        res = response.json()
        return {
            "종목명": res["stk_nm"],
            "현재가": abs(float(res["cur_prc"])),
            "상한가": abs(int(res["upl_pric"])),
            "하한가": abs(int(res["lst_pric"])),
        }

    # ── 분봉 차트 조회 (ka10080) ──────────────────────────
    @log_exceptions
    def get_minute_chart(self, stock_code: str, interval: str = "1") -> pd.DataFrame:
        """interval: '1', '3', '5', '10', '15', '30', '60'"""
        data = {
            "stk_cd": stock_code,
            "tic_scope": interval,
            "upd_stkpc_tp": "1",
        }
        response = requests.post(
            self.host + "/api/dostk/chart",
            headers=self._make_headers("ka10080"),
            json=data,
        )
        response.raise_for_status()
        res = response.json()["stk_min_pole_chart_qry"]
        df = pd.DataFrame(res)[::-1].reset_index(drop=True)
        for col in ["open_pric", "high_pric", "low_pric", "cur_prc", "trde_qty"]:
            df[col] = df[col].apply(lambda x: abs(int(x)))
        df.rename(columns={
            "cntr_tm": "Date", "open_pric": "Open", "high_pric": "High",
            "low_pric": "Low", "cur_prc": "Close", "trde_qty": "Volume",
        }, inplace=True)
        return df[["Date", "Open", "High", "Low", "Close", "Volume"]]

    # ── 계좌 잔고 조회 (kt00018) ──────────────────────────
    @log_exceptions
    def get_account_balance(self) -> tuple[dict, pd.DataFrame]:
        params = {"qry_tp": "1", "dmst_stex_tp": "KRX"}
        dfs, next_key, has_next = [], "", False
        while True:
            time.sleep(0.5)
            response = requests.post(
                self.host + "/api/dostk/acnt",
                headers=self._make_headers("kt00018", "Y" if has_next else "N", next_key),
                json=params,
            )
            response.raise_for_status()
            res = response.json()
            has_next = response.headers.get("cont-yn") == "Y"
            next_key = response.headers.get("next-key", "")
            account_info = {
                "총매입금액": int(res["tot_pur_amt"]),
                "총평가금액": int(res["tot_evlt_amt"]),
                "총평가손익": int(res["tot_evlt_pl"]),
                "총수익률": float(res["tot_prft_rt"]),
                "추정예탁자산": int(res["prsm_dpst_aset_amt"]),
            }
            df = pd.DataFrame(res["acnt_evlt_remn_indv_tot"])
            dfs.append(df)
            if not has_next:
                break
        all_df = pd.concat(dfs).reset_index(drop=True) if dfs else pd.DataFrame()
        return account_info, all_df

    # ── 매수 주문 (kt10000) ───────────────────────────────
    @log_exceptions
    def buy_order(self, stock_code: str, qty: int, price: int = 0, order_type: str = "3"):
        """order_type: '1'=지정가, '3'=시장가"""
        data = {
            "dmst_stex_tp": "KRX",
            "stk_cd": stock_code,
            "buy_sell_tp": "2",       # 2: 매수
            "trde_tp": order_type,
            "ord_qty": str(qty),
            "ord_pric": str(price),
        }
        response = requests.post(
            self.host + "/api/dostk/ordr",
            headers=self._make_headers("kt10000"),
            json=data,
        )
        response.raise_for_status()
        logger.info(f"[매수] {stock_code} {qty}주 | 결과: {response.json()}")
        return response.json()

    # ── 매도 주문 (kt10001) ───────────────────────────────
    @log_exceptions
    def sell_order(self, stock_code: str, qty: int, price: int = 0, order_type: str = "3"):
        """order_type: '1'=지정가, '3'=시장가"""
        data = {
            "dmst_stex_tp": "KRX",
            "stk_cd": stock_code,
            "buy_sell_tp": "1",       # 1: 매도
            "trde_tp": order_type,
            "ord_qty": str(qty),
            "ord_pric": str(price),
        }
        response = requests.post(
            self.host + "/api/dostk/ordr",
            headers=self._make_headers("kt10001"),
            json=data,
        )
        response.raise_for_status()
        logger.info(f"[매도] {stock_code} {qty}주 | 결과: {response.json()}")
        return response.json()

    # ── 등락률 상위 종목 조회 (ka10027) ───────────────────
    @log_exceptions
    def get_top_fluctuation(self, sort: str = "1") -> pd.DataFrame:
        """sort: '1'=상승률, '2'=상승폭, '3'=하락률, '4'=하락폭"""
        params = {
            "mrkt_tp": "000", "sort_tp": sort,
            "trde_qty_cnd": "0000", "stk_cnd": "1",
            "crd_cnd": "0", "updown_incls": "0",
            "pric_cnd": "0", "trde_prica_cnd": "0", "stex_tp": "3",
        }
        response = requests.post(
            self.host + "/api/dostk/rkinfo",
            headers=self._make_headers("ka10027"),
            json=params,
        )
        response.raise_for_status()
        df = pd.DataFrame(response.json()["pred_pre_flu_rt_upper"])
        df.rename(columns={
            "stk_cd": "종목코드", "stk_nm": "종목명",
            "cur_prc": "현재가", "flu_rt": "등락률",
            "now_trde_qty": "거래량",
        }, inplace=True)
        df["종목코드"] = df["종목코드"].str.replace("_AL", "").str.replace("A", "")
        return df
