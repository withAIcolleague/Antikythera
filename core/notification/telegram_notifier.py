"""
텔레그램 알림 모듈
매수/매도/에러 등 주요 이벤트를 텔레그램으로 전송
"""
import requests
from loguru import logger

from config.settings import TELEGRAM


class TelegramNotifier:
    def __init__(self, state_writer=None):
        self.enabled = TELEGRAM.get("enabled", False)
        self.bot_token = TELEGRAM.get("bot_token", "")
        self.chat_id = TELEGRAM.get("chat_id", "")
        self._state = state_writer  # StateWriter 주입 (optional)

    def _send(self, text: str):
        if not self.enabled or not self.bot_token or not self.chat_id:
            logger.debug(f"[텔레그램 비활성] {text}")
            return
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            requests.post(url, json={"chat_id": self.chat_id, "text": text}, timeout=5)
        except Exception as e:
            logger.warning(f"텔레그램 전송 실패: {e}")

    def notify_buy(self, stock_code: str, stock_name: str, qty: int, price: float, strategy: str):
        msg = (
            f"🟢 [매수 체결]\n"
            f"종목: {stock_name}({stock_code})\n"
            f"수량: {qty}주 | 가격: {price:,.0f}원\n"
            f"전략: {strategy}"
        )
        logger.info(msg)
        self._send(msg)
        if self._state:
            self._state.add_trade({
                "side": "BUY", "code": stock_code, "name": stock_name,
                "qty": qty, "price": price, "strategy": strategy,
            })

    def notify_sell(self, stock_code: str, stock_name: str, qty: int, price: float,
                    profit_pct: float, strategy: str):
        emoji = "🔴" if profit_pct < 0 else "🔵"
        msg = (
            f"{emoji} [매도 체결]\n"
            f"종목: {stock_name}({stock_code})\n"
            f"수량: {qty}주 | 가격: {price:,.0f}원\n"
            f"수익률: {profit_pct:+.2f}% | 전략: {strategy}"
        )
        logger.info(msg)
        self._send(msg)
        if self._state:
            self._state.add_trade({
                "side": "SELL", "code": stock_code, "name": stock_name,
                "qty": qty, "price": price, "strategy": strategy,
                "profit_pct": profit_pct,
            })

    def notify_disclosure(self, title: str, signal: str, corp_name: str = ""):
        emoji = "📢" if signal == "BUY" else ("⚠️" if signal == "SELL" else "📋")
        msg = (
            f"{emoji} [공시 감지]\n"
            f"회사: {corp_name}\n"
            f"내용: {title}\n"
            f"신호: {signal}"
        )
        logger.info(msg)
        self._send(msg)

    def notify_daily_summary(self, summary: dict):
        msg = (
            f"📊 [일일 결산]\n"
            f"총평가금액: {summary.get('총평가금액', 0):,.0f}원\n"
            f"총평가손익: {summary.get('총평가손익', 0):+,.0f}원\n"
            f"총수익률: {summary.get('총수익률', 0):+.2f}%"
        )
        logger.info(msg)
        self._send(msg)

    def notify_error(self, message: str):
        msg = f"🚨 [오류 발생]\n{message}"
        logger.error(msg)
        self._send(msg)
