"""
KRX KIND 공시 모니터링 모듈 (단타 대응)
공시 발생 시 콜백으로 신호 전달
"""
import re
import time
import threading
import requests
from bs4 import BeautifulSoup
from loguru import logger

from config.settings import DATA_SOURCE


class DisclosureMonitor:
    """KRX KIND 실시간 공시 모니터링"""

    KIND_URL = "https://kind.krx.co.kr/disclosure/todaydisclosure.do"

    # 단타 매수 키워드
    BUY_KEYWORDS = [
        "자사주", "자기주식취득", "최대실적", "영업이익증가",
        "수주", "계약체결", "합병", "인수", "특허", "FDA",
        "흑자전환", "사상최대", "최대매출",
    ]
    # 단타 매도/회피 키워드
    SELL_KEYWORDS = [
        "영업손실", "적자전환", "유상증자", "전환사채",
        "횡령", "배임", "상장폐지", "감사의견거절", "불성실공시",
    ]
    # 무시할 공시 (노이즈)
    SKIP_KEYWORDS = [
        "시간외단일가", "경쟁매매", "기타시장안내",
        "대량보유상황", "임원ㆍ주요주주", "분기보고서", "사업보고서",
    ]

    def __init__(self, callback=None, stock_lookup=None):
        """
        callback: 새 공시 발생 시 호출 함수 (disclosure: dict)
        stock_lookup: StockLookup 인스턴스 (회사명→종목코드 변환)
        """
        self.callback = callback
        self.stock_lookup = stock_lookup
        self._seen_ids: set[str] = set()
        self._running = False
        self._thread = None
        self.interval = DATA_SOURCE.get("disclosure_interval_sec", 30)
        self._headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

    def _fetch_disclosures(self) -> list[dict]:
        """KIND 오늘 공시 목록 파싱"""
        try:
            resp = requests.post(
                self.KIND_URL,
                data={
                    "method": "searchTodayDisclosureSub",
                    "currentPageSize": "30",
                    "pageIndex": "1",
                    "forward": "todaydisclosure_sub",
                },
                headers=self._headers,
                timeout=10,
            )
            resp.encoding = "utf-8"
            soup = BeautifulSoup(resp.text, "lxml")
            rows = soup.select("table.list tbody tr")

            results = []
            for row in rows:
                cols = row.select("td")
                if not cols or len(cols) < 3:
                    continue

                time_str = cols[0].get_text(strip=True)
                corp_name = cols[1].get_text(strip=True)
                title = cols[2].get_text(strip=True)

                # 공시 ID 추출 (openDisclsViewer('XXXXX',''))
                disc_id = ""
                corp_code = ""
                for a in row.select("a[onclick]"):
                    onclick = a.get("onclick", "")
                    m = re.search(r"openDisclsViewer\('(\w+)'", onclick)
                    if m:
                        disc_id = m.group(1)
                    m2 = re.search(r"companysummary_open\('(\w+)'\)", onclick)
                    if m2:
                        corp_code = m2.group(1)

                if not disc_id:
                    continue

                # 종목코드 조회
                stock_code = ""
                if self.stock_lookup and corp_name:
                    stock_code = self.stock_lookup.get_code(corp_name) or ""

                results.append({
                    "id": disc_id,
                    "time": time_str,
                    "corp_name": corp_name,
                    "corp_code": corp_code,
                    "stock_code": stock_code,
                    "title": title,
                })
            return results

        except Exception as e:
            logger.warning(f"공시 조회 실패: {e}")
            return []

    def _classify(self, title: str) -> str:
        """공시 제목 분류: 'BUY' | 'SELL' | 'SKIP' | 'NEUTRAL'"""
        for kw in self.SKIP_KEYWORDS:
            if kw in title:
                return "SKIP"
        for kw in self.SELL_KEYWORDS:
            if kw in title:
                return "SELL"
        for kw in self.BUY_KEYWORDS:
            if kw in title:
                return "BUY"
        return "NEUTRAL"

    def _monitor_loop(self):
        logger.info("공시 모니터링 시작 (KRX KIND)")
        while self._running:
            disclosures = self._fetch_disclosures()
            new_count = 0
            for item in disclosures:
                disc_id = item["id"]
                if disc_id in self._seen_ids:
                    continue
                self._seen_ids.add(disc_id)
                signal = self._classify(item["title"])
                item["signal"] = signal

                if signal == "SKIP":
                    continue

                new_count += 1
                logger.info(
                    f"[공시] {item['time']} | {item['corp_name']} "
                    f"| {item['title'][:40]} | 신호={signal}"
                )
                if self.callback:
                    self.callback(item)

            if new_count:
                logger.debug(f"신규 공시 {new_count}건 처리")
            time.sleep(self.interval)
        logger.info("공시 모니터링 종료")

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
