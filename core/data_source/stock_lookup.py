"""
회사명 → 종목코드 매핑 테이블
기존 KiwoomAPI 인스턴스의 토큰을 재사용해서 로그인 중복 방지
"""
import time
import requests
from loguru import logger
from config.settings import IS_PAPER_TRADING

HOST = "https://mockapi.kiwoom.com" if IS_PAPER_TRADING else "https://api.kiwoom.com"


class StockLookup:
    def __init__(self):
        self._map: dict[str, str] = {}

    def load(self, token: str):
        """
        앱 시작 시 1회 호출
        token: KiwoomAPI에서 발급받은 토큰 (재사용)
        """
        self._map = self._build_map(token)

    def _build_map(self, token: str) -> dict[str, str]:
        name_map: dict[str, str] = {}
        for mrkt_tp in ["0", "1"]:
            try:
                resp = requests.post(
                    HOST + "/api/dostk/stkinfo",
                    headers={
                        "Content-Type": "application/json;charset=UTF-8",
                        "authorization": f"Bearer {token}",
                        "cont-yn": "N",
                        "next-key": "",
                        "api-id": "ka10099",
                    },
                    json={"mrkt_tp": mrkt_tp, "inds_cd": ""},
                    timeout=15,
                )
                resp.raise_for_status()
                stocks = resp.json().get("list") or []
                for s in stocks:
                    code = s.get("code", "").replace("A", "").strip()
                    name = s.get("name", "").strip()
                    if code and name:
                        name_map[name] = code
                logger.info(f"{'코스피' if mrkt_tp=='0' else '코스닥'} 종목 {len(stocks)}개 로드")
                time.sleep(1)  # 키움 API rate limit 방지
            except Exception as e:
                logger.warning(f"종목 리스트 조회 실패 (mrkt_tp={mrkt_tp}): {e}")
        logger.info(f"전체 종목 매핑 완료: {len(name_map)}개")
        return name_map

    def get_code(self, company_name: str) -> str | None:
        code = self._map.get(company_name)
        if code:
            return code
        for name, c in self._map.items():
            if company_name in name or name in company_name:
                return c
        return None
