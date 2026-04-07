"""
단타 전략 엔진
공시 감지 + 기술적 지표 조합으로 매매 신호 생성 및 주문 실행
"""
import time
import threading
from datetime import datetime
from loguru import logger

from core.api.kiwoom_api import KiwoomAPI
from core.indicators.technical import TechnicalIndicators
from core.data_source.disclosure_monitor import DisclosureMonitor
from core.data_source.stock_lookup import StockLookup
from core.risk.capital_manager import CapitalManager
from core.notification.telegram_notifier import TelegramNotifier
from config.settings import RISK, DAYTRADING_FILTER


class Position:
    """보유 포지션 정보"""
    def __init__(self, stock_code: str, stock_name: str, qty: int, buy_price: float):
        self.stock_code = stock_code
        self.stock_name = stock_name
        self.qty = qty
        self.buy_price = buy_price
        self.highest_price = buy_price  # 트레일링 스탑용 최고가

    def profit_pct(self, current_price: float) -> float:
        return (current_price - self.buy_price) / self.buy_price * 100


class DayTradingEngine:
    def __init__(self, api: KiwoomAPI, capital_mgr: CapitalManager, notifier: TelegramNotifier,
                 stock_lookup: StockLookup):
        self.api = api
        self.capital_mgr = capital_mgr
        self.notifier = notifier
        self.indicators = TechnicalIndicators(mode="daytrading")
        self.positions: dict[str, Position] = {}  # 보유 포지션 {종목코드: Position}
        self._running = False

        # 리스크 설정
        self.stop_loss_pct = RISK["stop_loss_pct"]
        self.trailing_stop_pct = RISK["trailing_stop_pct"]
        self.max_positions = DAYTRADING_FILTER["max_positions"]

        # 공시 모니터링 (외부에서 주입받은 stock_lookup 사용)
        self.disclosure_monitor = DisclosureMonitor(
            callback=self._on_disclosure,
            stock_lookup=stock_lookup,
        )

    # ── 공시 수신 시 처리 ─────────────────────────────────
    def _on_disclosure(self, disclosure: dict):
        if disclosure.get("signal") != "BUY":
            return

        stock_code = disclosure.get("stock_code", "")
        stock_name = disclosure.get("corp_name", "")
        title = disclosure.get("title", "")

        if not stock_code:
            logger.info(f"[공시] 종목코드 없음 ({stock_name}): {title[:40]}")
            return

        if stock_code in self.positions:
            logger.info(f"[공시] {stock_name} 이미 보유 중, 스킵")
            return

        if len(self.positions) >= self.max_positions:
            logger.info(f"[공시] 최대 보유 종목 수 초과({self.max_positions}개), 스킵")
            return

        logger.info(f"[공시 BUY 신호] {stock_name}({stock_code}): {title}")
        self.notifier.notify_disclosure(title, "BUY", stock_name)

        # 필터 + 기술적 지표로 재확인
        self._evaluate_and_buy(stock_code, stock_name, reason=f"공시: {title}")

    # ── 단타 필터 통과 여부 확인 ──────────────────────────
    def _pass_filter(self, stock_code: str, current_price: float) -> bool:
        """시가총액, 거래량, 종목 상태 필터"""
        try:
            # 등락률 상위 종목 리스트에서 거래량 확인
            top_df = self.api.get_top_fluctuation()
            if top_df is not None and not top_df.empty:
                row = top_df[top_df["종목코드"] == stock_code]
                if not row.empty:
                    volume = int(row.iloc[0].get("거래량", 0))
                    if volume < DAYTRADING_FILTER["min_volume"]:
                        logger.info(f"[필터] {stock_code} 거래량 부족: {volume:,}")
                        return False
            return True
        except Exception as e:
            logger.warning(f"[필터] {stock_code} 필터 확인 오류: {e}")
            return True  # 오류 시 통과 허용

    # ── 기술적 지표 확인 후 매수 ──────────────────────────
    def _evaluate_and_buy(self, stock_code: str, stock_name: str, reason: str = ""):
        try:
            # 1분봉 차트 조회
            df = self.api.get_minute_chart(stock_code, interval="1")
            if df is None or len(df) < 20:
                logger.warning(f"[{stock_code}] 차트 데이터 부족")
                return

            # 지표 계산 및 신호 확인
            df = self.indicators.add_all(df)
            signal = self.indicators.get_signal(df)

            if signal != "BUY":
                logger.info(f"[{stock_code}] 기술적 지표 신호 없음 ({signal}), 매수 보류")
                return

            # 현재가 조회
            price_info = self.api.get_stock_price(stock_code)
            if price_info is None:
                return

            current_price = price_info["현재가"]

            # 단타 필터 통과 확인
            if not self._pass_filter(stock_code, current_price):
                return
            # 매수 수량 계산
            qty = self.capital_mgr.get_max_position_size("daytrading", current_price)
            if qty <= 0:
                logger.warning(f"[{stock_code}] 매수 수량 0, 스킵")
                return

            logger.info(f"[단타 매수] {stock_name}({stock_code}) {qty}주 @ {current_price:,.0f}원 | {reason}")

            # 시장가 매수
            self.api.buy_order(stock_code, qty, order_type="3")
            self.positions[stock_code] = Position(stock_code, stock_name, qty, current_price)
            self.notifier.notify_buy(stock_code, stock_name, qty, current_price, "단타")

        except Exception as e:
            logger.error(f"[{stock_code}] 매수 처리 오류: {e}")

    # ── 포지션 모니터링 (손절/트레일링 스탑) ──────────────
    def _monitor_positions(self):
        while self._running:
            for stock_code, pos in list(self.positions.items()):
                try:
                    price_info = self.api.get_stock_price(stock_code)
                    if price_info is None:
                        continue
                    current_price = price_info["현재가"]
                    profit_pct = pos.profit_pct(current_price)

                    # 최고가 갱신 (트레일링 스탑용)
                    if current_price > pos.highest_price:
                        pos.highest_price = current_price

                    # 손절 (-stop_loss_pct%)
                    if profit_pct <= -self.stop_loss_pct:
                        logger.warning(f"[손절] {pos.stock_name} {profit_pct:.2f}%")
                        self._sell(pos, current_price, reason="손절")
                        continue

                    # 트레일링 스탑 (최고가 대비 -trailing_stop_pct%)
                    trailing_drop = (pos.highest_price - current_price) / pos.highest_price * 100
                    if trailing_drop >= self.trailing_stop_pct and profit_pct > 0:
                        logger.info(f"[트레일링 스탑] {pos.stock_name} 최고가 대비 -{trailing_drop:.2f}%")
                        self._sell(pos, current_price, reason="트레일링 스탑")
                        continue

                except Exception as e:
                    logger.error(f"[{stock_code}] 포지션 모니터링 오류: {e}")

            time.sleep(10)  # 10초마다 체크

    def _sell(self, pos: Position, current_price: float, reason: str = ""):
        try:
            self.api.sell_order(pos.stock_code, pos.qty, order_type="3")
            profit_pct = pos.profit_pct(current_price)
            self.notifier.notify_sell(
                pos.stock_code, pos.stock_name, pos.qty, current_price, profit_pct,
                strategy=f"단타({reason})"
            )
            del self.positions[pos.stock_code]
        except Exception as e:
            logger.error(f"[{pos.stock_code}] 매도 오류: {e}")

    # ── 장 마감 시 전체 청산 ──────────────────────────────
    def close_all_positions(self):
        logger.info(f"[단타 엔진] 장 마감 청산 시작 ({len(self.positions)}개 포지션)")
        for stock_code, pos in list(self.positions.items()):
            try:
                price_info = self.api.get_stock_price(stock_code)
                current_price = price_info["현재가"] if price_info else pos.buy_price
                self._sell(pos, current_price, reason="장마감")
            except Exception as e:
                logger.error(f"[{stock_code}] 장마감 청산 오류: {e}")

    # ── 엔진 시작/정지 ────────────────────────────────────
    def start(self):
        self._running = True
        self.disclosure_monitor.start()

        monitor_thread = threading.Thread(target=self._monitor_positions, daemon=True)
        monitor_thread.start()

        logger.info("[단타 엔진] 시작 완료 - 공시 모니터링 + 포지션 감시 중")

    def stop(self):
        self._running = False
        self.disclosure_monitor.stop()
        logger.info("[단타 엔진] 정지")

    def status(self) -> str:
        if not self.positions:
            return "보유 포지션 없음"
        lines = ["[단타 보유 포지션]"]
        for code, pos in self.positions.items():
            lines.append(f"  {pos.stock_name}({code}): {pos.qty}주 @ {pos.buy_price:,.0f}원")
        return "\n".join(lines)
