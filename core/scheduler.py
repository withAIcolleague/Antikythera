"""
장 시작/종료 스케줄러
국내장(9:00~15:30)과 미국장(22:30~05:00 KST) 자동 관리
"""
import time
from datetime import datetime, date
import threading
from loguru import logger


class MarketScheduler:
    """
    국내장 / 미국장 시간대 관리 및 이벤트 콜백 실행
    """

    # ── 국내장 시간 (KST) ─────────────────────────────────
    KR_PREMARKET = (8, 50)   # 8:50 사전 점검
    KR_OPEN  = (9,  0)       # 9:00 장 시작
    KR_SCAN  = (9,  5)       # 9:05 스윙 모닝 스캔
    KR_CLOSE_WARN = (15, 20) # 15:20 단타 청산 준비
    KR_CLOSE = (15, 30)      # 15:30 장 마감

    # ── 미국장 시간 (KST 기준) ────────────────────────────
    US_PRE   = (22, 25)  # 22:25 미국 프리마켓 준비
    US_OPEN  = (22, 30)  # 22:30 미국 정규장 시작
    US_CLOSE = ( 5,  0)  # 05:00 미국 정규장 종료 (다음날)

    def __init__(self):
        self._callbacks: dict[str, list] = {
            "kr_premarket":  [],   # 사전 점검 (8:50)
            "kr_open":       [],   # 국내장 시작 (9:00)
            "kr_scan":       [],   # 스윙 모닝 스캔 (9:05)
            "kr_close_warn": [],   # 단타 청산 준비 (15:20)
            "kr_close":      [],   # 국내장 마감 (15:30)
            "us_open":       [],   # 미국장 시작 (22:25)
            "us_close":      [],   # 미국장 종료 (05:00)
            "daily_report":  [],   # 일일 결산 (16:00)
        }
        self._fired: dict[str, date | None] = {k: None for k in self._callbacks}
        self._running = False

    def on(self, event: str, callback):
        """이벤트 콜백 등록"""
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def _fire(self, event: str):
        today = date.today()
        if self._fired[event] == today:
            return  # 오늘 이미 실행
        self._fired[event] = today
        logger.info(f"[스케줄러] 이벤트 발생: {event}")
        for cb in self._callbacks[event]:
            try:
                cb()
            except Exception as e:
                logger.error(f"[스케줄러] {event} 콜백 오류: {e}")

    @staticmethod
    def is_weekday() -> bool:
        return datetime.now().weekday() < 5  # 월~금

    @staticmethod
    def is_holiday() -> bool:
        """
        공휴일 체크 (현재는 단순 주말만 체크)
        추후 한국 공휴일 API 연동 가능
        """
        return not MarketScheduler.is_weekday()

    def _time_match(self, h: int, m: int) -> bool:
        now = datetime.now()
        return now.hour == h and now.minute == m

    def _loop(self):
        logger.info("[스케줄러] 시작")
        while self._running:
            now = datetime.now()

            if not self.is_holiday():
                # 국내장 이벤트
                if self._time_match(*self.KR_PREMARKET):
                    self._fire("kr_premarket")
                if self._time_match(*self.KR_OPEN):
                    self._fire("kr_open")
                if self._time_match(*self.KR_SCAN):
                    self._fire("kr_scan")
                if self._time_match(*self.KR_CLOSE_WARN):
                    self._fire("kr_close_warn")
                if self._time_match(*self.KR_CLOSE):
                    self._fire("kr_close")

                # 일일 결산 (16:00)
                if self._time_match(16, 0):
                    self._fire("daily_report")

                # 미국장 이벤트
                if self._time_match(*self.US_PRE):
                    self._fire("us_open")

            # 미국장 종료 (새벽 5시, 주말 여부 무관)
            if self._time_match(*self.US_CLOSE):
                self._fire("us_close")

            time.sleep(30)  # 30초마다 체크
        logger.info("[스케줄러] 종료")

    def start(self):
        self._running = True
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def stop(self):
        self._running = False

    def market_status(self) -> str:
        """현재 장 상태 반환"""
        now = datetime.now()
        h, m = now.hour, now.minute
        total_min = h * 60 + m

        kr_open_min  = self.KR_OPEN[0]  * 60 + self.KR_OPEN[1]
        kr_close_min = self.KR_CLOSE[0] * 60 + self.KR_CLOSE[1]
        us_open_min  = self.US_PRE[0]   * 60 + self.US_PRE[1]

        if self.is_holiday():
            return "휴장 (주말/공휴일)"
        if kr_open_min <= total_min < kr_close_min:
            return "국내장 운영중"
        if total_min >= us_open_min or total_min < self.US_CLOSE[0] * 60:
            return "미국장 운영중"
        return "장외 시간"
