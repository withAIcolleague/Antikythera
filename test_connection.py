"""
키움/한국투자증권 API 연결 테스트
"""
import sys
import io

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import requests
from loguru import logger
from config.settings import KIWOOM, KR_INVEST, IS_PAPER_TRADING

logger.remove()
logger.add(sys.stdout, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}")

KIWOOM_HOST = "https://mockapi.kiwoom.com" if IS_PAPER_TRADING else "https://api.kiwoom.com"
KR_INVEST_HOST = "https://openapivts.koreainvestment.com:29443" if IS_PAPER_TRADING else "https://openapi.koreainvestment.com:9443"


def test_kiwoom():
    logger.info(f"[키움] 연결 테스트 시작 ({'모의투자' if IS_PAPER_TRADING else '실전투자'})")
    try:
        response = requests.post(
            KIWOOM_HOST + "/oauth2/token",
            headers={"Content-Type": "application/json;charset=UTF-8"},
            json={
                "grant_type": "client_credentials",
                "appkey": KIWOOM["api_key"],
                "secretkey": KIWOOM["api_secret_key"],
            },
            timeout=10,
        )
        response.raise_for_status()
        token = response.json().get("token", "")
        if token:
            logger.success(f"[키움] 로그인 성공! 토큰: {token[:20]}...")
            return token
        else:
            logger.error(f"[키움] 토큰 없음. 응답: {response.json()}")
    except Exception as e:
        logger.error(f"[키움] 연결 실패: {e}")
    return None


def test_kiwoom_balance(token: str):
    logger.info("[키움] 계좌 잔고 조회 테스트")
    try:
        response = requests.post(
            KIWOOM_HOST + "/api/dostk/acnt",
            headers={
                "Content-Type": "application/json;charset=UTF-8",
                "authorization": f"Bearer {token}",
                "cont-yn": "N",
                "next-key": "",
                "api-id": "kt00018",
            },
            json={"qry_tp": "1", "dmst_stex_tp": "KRX"},
            timeout=10,
        )
        response.raise_for_status()
        res = response.json()
        logger.success(f"[키움] 잔고 조회 성공!")
        logger.info(f"  추정예탁자산: {int(res.get('prsm_dpst_aset_amt', 0)):,}원")
        logger.info(f"  총평가금액:   {int(res.get('tot_evlt_amt', 0)):,}원")
        logger.info(f"  총평가손익:   {int(res.get('tot_evlt_pl', 0)):,}원")
    except Exception as e:
        logger.error(f"[키움] 잔고 조회 실패: {e}")


def test_kr_invest():
    logger.info(f"[한국투자] 연결 테스트 시작 ({'모의투자' if IS_PAPER_TRADING else '실전투자'})")
    try:
        response = requests.post(
            KR_INVEST_HOST + "/oauth2/tokenP",
            headers={"Content-Type": "application/json"},
            json={
                "grant_type": "client_credentials",
                "appkey": KR_INVEST["api_key"],
                "appsecret": KR_INVEST["api_secret_key"],
            },
            timeout=10,
        )
        response.raise_for_status()
        token = response.json().get("access_token", "")
        if token:
            logger.success(f"[한국투자] 로그인 성공! 토큰: {token[:20]}...")
        else:
            logger.error(f"[한국투자] 토큰 없음. 응답: {response.json()}")
    except Exception as e:
        logger.error(f"[한국투자] 연결 실패: {e}")


if __name__ == "__main__":
    print("=" * 50)
    print(f" Antikythera 연결 테스트 ({'모의투자' if IS_PAPER_TRADING else '실전투자'})")
    print("=" * 50)

    # 키움 테스트
    token = test_kiwoom()
    if token:
        test_kiwoom_balance(token)

    print()

    # 한국투자 테스트
    test_kr_invest()
