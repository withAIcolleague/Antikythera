"""
스윙 전략 엔진
관심종목 일봉 기술적 지표 기반 매매 + 뉴스 보조
국내(키움) / 미국(한국투자) 분리 운용
"""
import time
import threading
from loguru import logger

from core.api.kiwoom_api import KiwoomAPI
from core.api.kr_invest_api import KRInvestAPI
from core.indicators.technical import TechnicalIndicators
from core.risk.capital_manager import CapitalManager
from core.notification.telegram_notifier import TelegramNotifier
from config.settings import SWING_WATCHLIST, RISK


# 미국 주식 거래소 자동 판별 (간단 매핑, 필요시 확장)
US_EXCHANGE_MAP = {
    "ASTS": "NAS", "IRDM": "NAS", "GSAT": "NAS", "SATS": "NAS",
    "TSAT": "NAS", "PL": "NAS", "LUNR": "NAS", "RKLB": "NAS",
    "LMT": "NYS", "NOC": "NYS", "AIR": "NYS",
    "AMZN": "NAS", "AAPL": "NAS", "VSAT": "NAS",
}


class SwingPosition:
    def __init__(self, code: str, name: str, qty: int, buy_price: float, market: str):
        self.code = code          # 종목코드 or 티커
        self.name = name
        self.qty = qty
        self.buy_price = buy_price
        self.market = market      # "kr" or "us"
        self.highest_price = buy_price

    def profit_pct(self, current_price: float) -> float:
        return (current_price - self.buy_price) / self.buy_price * 100


class SwingEngine:
    def __init__(
        self,
        kiwoom_api: KiwoomAPI,
        kr_invest_api: KRInvestAPI,
        capital_mgr: CapitalManager,
        notifier: TelegramNotifier,
    ):
        self.kiwoom = kiwoom_api
        self.kr_invest = kr_invest_api
        self.capital_mgr = capital_mgr
        self.notifier = notifier
        self.indicators = TechnicalIndicators(mode="swing")
        self.positions: dict[str, SwingPosition] = {}
        self._running = False

        self.stop_loss_pct = RISK["stop_loss_pct"] + 1.0      # 스윙은 손절 여유 +1%
        self.trailing_stop_pct = RISK["trailing_stop_pct"] + 2.0  # 트레일링 스탑 +2%

        self.kr_watchlist = SWING_WATCHLIST.get("kr", [])
        self.us_watchlist = SWING_WATCHLIST.get("us", [])

    # ── 국내 종목 스캔 ────────────────────────────────────
    def _scan_kr(self):
        logger.info(f"[스윙-국내] 관심종목 스캔 시작 ({len(self.kr_watchlist)}개)")
        for stock in self.kr_watchlist:
            code = stock.get("code", "")
            name = stock.get("name", "")
            if not code:
                continue
            if code in self.positions:
                continue
            try:
                df = self.kiwoom.get_minute_chart(code, interval="60")  # 60분봉 (일봉 대용)
                if df is None or len(df) < 20:
                    logger.debug(f"[스윙-국내] {name} 데이터 부족, 스킵")
                    continue

                df = self.indicators.add_all(df)
                signal = self.indicators.get_signal(df)

                if signal == "BUY":
                    price_info = self.kiwoom.get_stock_price(code)
                    if price_info is None:
                        continue
                    price = price_info["현재가"]
                    qty = self.capital_mgr.get_max_position_size("swing", price)
                    if qty <= 0:
                        continue
                    logger.info(f"[스윙-국내 매수] {name}({code}) {qty}주 @ {price:,.0f}원")
                    self.kiwoom.buy_order(code, qty, order_type="3")
                    self.positions[code] = SwingPosition(code, name, qty, price, "kr")
                    self.notifier.notify_buy(code, name, qty, price, "스윙-국내")

                time.sleep(0.5)  # API 호출 간격
            except Exception as e:
                logger.error(f"[스윙-국내] {name}({code}) 스캔 오류: {e}")

    # ── 미국 종목 스캔 ────────────────────────────────────
    def _scan_us(self):
        logger.info(f"[스윙-미국] 관심종목 스캔 시작 ({len(self.us_watchlist)}개)")
        for stock in self.us_watchlist:
            ticker = stock.get("ticker", "")
            name = stock.get("name", "")
            if not ticker:
                continue
            if ticker in self.positions:
                continue
            try:
                exchange = US_EXCHANGE_MAP.get(ticker, "NAS")
                df = self.kr_invest.get_us_daily_chart(ticker, exchange=exchange, count=60)
                if df is None or len(df) < 20:
                    logger.debug(f"[스윙-미국] {name} 데이터 부족, 스킵")
                    continue

                df = self.indicators.add_all(df)
                signal = self.indicators.get_signal(df)

                if signal == "BUY":
                    price_info = self.kr_invest.get_us_stock_price(ticker, exchange=exchange)
                    if price_info is None:
                        continue
                    price_usd = price_info["현재가"]
                    # 달러→원 환산 (임시 1,350원 고정, 추후 실시간 환율 연동)
                    price_krw = price_usd * 1350
                    qty = self.capital_mgr.get_max_position_size("swing", price_krw)
                    if qty <= 0:
                        continue
                    logger.info(f"[스윙-미국 매수] {name}({ticker}) {qty}주 @ ${price_usd:.2f}")
                    self.kr_invest.buy_us_stock(ticker, qty, exchange=exchange)
                    self.positions[ticker] = SwingPosition(ticker, name, qty, price_usd, "us")
                    self.notifier.notify_buy(ticker, name, qty, price_usd, "스윙-미국")

                time.sleep(0.5)
            except Exception as e:
                logger.error(f"[스윙-미국] {name}({ticker}) 스캔 오류: {e}")

    # ── 포지션 모니터링 (30분마다) ────────────────────────
    def _monitor_positions(self):
        while self._running:
            for key, pos in list(self.positions.items()):
                try:
                    if pos.market == "kr":
                        price_info = self.kiwoom.get_stock_price(pos.code)
                        current_price = price_info["현재가"] if price_info else None
                    else:
                        exchange = US_EXCHANGE_MAP.get(pos.code, "NAS")
                        price_info = self.kr_invest.get_us_stock_price(pos.code, exchange)
                        current_price = price_info["현재가"] if price_info else None

                    if current_price is None:
                        continue

                    if current_price > pos.highest_price:
                        pos.highest_price = current_price

                    profit_pct = pos.profit_pct(current_price)

                    # 손절
                    if profit_pct <= -self.stop_loss_pct:
                        logger.warning(f"[스윙 손절] {pos.name} {profit_pct:.2f}%")
                        self._sell(pos, current_price, "손절")
                        continue

                    # 트레일링 스탑
                    trailing_drop = (pos.highest_price - current_price) / pos.highest_price * 100
                    if trailing_drop >= self.trailing_stop_pct and profit_pct > 0:
                        logger.info(f"[스윙 트레일링] {pos.name} 최고가 대비 -{trailing_drop:.2f}%")
                        self._sell(pos, current_price, "트레일링 스탑")

                except Exception as e:
                    logger.error(f"[스윙 모니터링] {key} 오류: {e}")

            time.sleep(1800)  # 30분마다 체크

    def _sell(self, pos: SwingPosition, current_price: float, reason: str):
        try:
            if pos.market == "kr":
                self.kiwoom.sell_order(pos.code, pos.qty, order_type="3")
            else:
                exchange = US_EXCHANGE_MAP.get(pos.code, "NAS")
                self.kr_invest.sell_us_stock(pos.code, pos.qty, exchange=exchange)

            profit_pct = pos.profit_pct(current_price)
            self.notifier.notify_sell(
                pos.code, pos.name, pos.qty, current_price,
                profit_pct, strategy=f"스윙-{pos.market.upper()}({reason})"
            )
            del self.positions[pos.code]
        except Exception as e:
            logger.error(f"[스윙 매도] {pos.name} 오류: {e}")

    # ── 장 시작 시 스캔 실행 ──────────────────────────────
    def run_morning_scan(self):
        """장 시작 후 호출 - 국내/미국 순차 스캔"""
        logger.info("[스윙 엔진] 모닝 스캔 시작")
        self._scan_kr()
        self._scan_us()
        logger.info(f"[스윙 엔진] 모닝 스캔 완료 | 보유 {len(self.positions)}개")

    # ── 엔진 시작/정지 ────────────────────────────────────
    def start(self):
        self._running = True
        monitor_thread = threading.Thread(target=self._monitor_positions, daemon=True)
        monitor_thread.start()
        logger.info("[스윙 엔진] 시작 완료 - 포지션 감시 중 (30분 주기)")

    def stop(self):
        self._running = False
        logger.info("[스윙 엔진] 정지")

    def status(self) -> str:
        if not self.positions:
            return "스윙 보유 포지션 없음"
        lines = ["[스윙 보유 포지션]"]
        for key, pos in self.positions.items():
            lines.append(f"  [{pos.market.upper()}] {pos.name}({key}): {pos.qty}주 @ {pos.buy_price:,.2f}")
        return "\n".join(lines)
