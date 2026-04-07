"""
Antikythera - 자동매매 시스템 진입점

실행 전 config/settings.py에서 API 키와 계좌번호를 설정하세요.
"""
import sys
import io
from loguru import logger

# Windows 터미널 한글 출력 설정
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import signal
import time

from config.settings import IS_PAPER_TRADING, TOTAL_CAPITAL
from core.api.kiwoom_api import KiwoomAPI
from core.api.kr_invest_api import KRInvestAPI
from core.risk.capital_manager import CapitalManager
from core.notification.telegram_notifier import TelegramNotifier
from core.strategy.daytrading.engine import DayTradingEngine
from core.strategy.swing.engine import SwingEngine
from core.scheduler import MarketScheduler
from core.premarket_check import PreMarketCheck
from core.data_source.stock_lookup import StockLookup
from core.state_writer import StateWriter


def setup_logger():
    logger.remove()
    logger.add(sys.stdout, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}")
    logger.add("logs/antikythera.log", rotation="1 day", retention="30 days", level="DEBUG")


def main():
    setup_logger()
    mode = "모의투자" if IS_PAPER_TRADING else "실전투자"
    logger.info(f"Antikythera 시작 - {mode} 모드")

    state = StateWriter()
    notifier = TelegramNotifier(state_writer=state)
    capital_mgr = CapitalManager(total_capital=TOTAL_CAPITAL)

    logger.info("자금 배분 현황:")
    for k, v in capital_mgr.summary().items():
        logger.info(f"  {k}: {v}")

    # API 연결
    logger.info("키움 API 연결 중...")
    kiwoom_api = KiwoomAPI()
    logger.info("한국투자증권 API 연결 중...")
    kr_invest_api = KRInvestAPI()

    # 전략 엔진 초기화
    logger.info("종목 리스트 로딩 중...")
    stock_lookup = StockLookup()
    stock_lookup.load(kiwoom_api.token)

    daytrading_engine = DayTradingEngine(kiwoom_api, capital_mgr, notifier, stock_lookup)
    swing_engine = SwingEngine(kiwoom_api, kr_invest_api, capital_mgr, notifier)
    premarket = PreMarketCheck(kiwoom_api, kr_invest_api, capital_mgr, notifier, stock_lookup)

    # 스케줄러 설정
    scheduler = MarketScheduler()

    scheduler.on("kr_premarket", lambda: premarket.run())
    scheduler.on("kr_open", lambda: (
        daytrading_engine.start(),
        state.set_daytrading_active(True),
        logger.info("[스케줄러] 국내장 시작 - 단타 엔진 가동")
    ))
    scheduler.on("kr_scan", lambda: (
        swing_engine.run_morning_scan(),
        logger.info("[스케줄러] 스윙 모닝 스캔 실행")
    ))
    scheduler.on("kr_close_warn", lambda: (
        logger.info("[스케줄러] 15:20 - 단타 청산 준비"),
        notifier._send("⏰ 15:20 - 단타 포지션 청산 준비 중")
    ))
    scheduler.on("kr_close", lambda: (
        daytrading_engine.close_all_positions(),
        daytrading_engine.stop(),
        state.set_daytrading_active(False),
        logger.info("[스케줄러] 국내장 마감 - 단타 엔진 정지")
    ))
    scheduler.on("daily_report", lambda: (
        notifier.notify_daily_summary({
            "총평가금액": capital_mgr.total_capital,
            "총평가손익": 0,
            "총수익률": 0.0,
        }),
        logger.info("[스케줄러] 일일 결산 발송")
    ))
    scheduler.on("us_open", lambda: (
        swing_engine.run_morning_scan(),
        logger.info("[스케줄러] 미국장 시작 - 스윙 스캔 실행")
    ))
    scheduler.on("us_close", lambda: (
        logger.info("[스케줄러] 미국장 종료"),
        notifier._send("🌙 미국장 종료")
    ))

    swing_engine.start()
    state.set_swing_active(True)
    scheduler.start()

    state.set_running(True)
    state.set_market_status(scheduler.market_status())
    logger.info(f"[스케줄러] 현재 장 상태: {scheduler.market_status()}")

    # Ctrl+C 종료 처리
    def shutdown(sig, frame):
        logger.info("종료 신호 수신 - 정리 중...")
        daytrading_engine.close_all_positions()
        daytrading_engine.stop()
        swing_engine.stop()
        scheduler.stop()
        state.clear()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logger.info("Antikythera 실행 중... (종료: Ctrl+C)")
    while True:
        time.sleep(30)
        # 주기적으로 상태 갱신
        try:
            state.set_market_status(scheduler.market_status())
            state.update_daytrading_positions(daytrading_engine.positions)
            state.update_swing_positions(swing_engine.positions)
            account_info, _ = kiwoom_api.get_account_balance()
            state.set_account(account_info)
            capital_mgr.update_capital(account_info.get("추정예탁자산", TOTAL_CAPITAL))
        except Exception as e:
            logger.warning(f"상태 갱신 오류: {e}")


if __name__ == "__main__":
    main()
