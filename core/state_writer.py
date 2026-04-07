"""
거래 시스템 상태를 JSON 파일로 기록
dashboard.py가 이 파일을 읽어 현황을 표시
"""
import json
import os
import time
from datetime import datetime
from pathlib import Path
from loguru import logger

STATE_FILE = Path(__file__).parent.parent / "trading_state.json"


class StateWriter:
    def __init__(self):
        self._state = {
            "pid": os.getpid(),
            "running": False,
            "started_at": None,
            "market_status": "알 수 없음",
            "daytrading": {"active": False, "positions": []},
            "swing": {"active": False, "positions": []},
            "account": {
                "total_asset": 0,
                "total_eval": 0,
                "total_profit": 0,
                "profit_rate": 0.0,
            },
            "today_trades": [],
            "last_update": None,
        }
        self._write()

    def _write(self):
        self._state["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            STATE_FILE.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"[StateWriter] 파일 쓰기 실패: {e}")

    def set_running(self, running: bool):
        self._state["running"] = running
        if running and not self._state["started_at"]:
            self._state["started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._write()

    def set_market_status(self, status: str):
        self._state["market_status"] = status
        self._write()

    def set_account(self, info: dict):
        self._state["account"] = {
            "total_asset": info.get("추정예탁자산", 0),
            "total_eval": info.get("총평가금액", 0),
            "total_profit": info.get("총평가손익", 0),
            "profit_rate": info.get("총수익률", 0.0),
        }
        self._write()

    def set_daytrading_active(self, active: bool):
        self._state["daytrading"]["active"] = active
        self._write()

    def set_swing_active(self, active: bool):
        self._state["swing"]["active"] = active
        self._write()

    def update_daytrading_positions(self, positions: dict):
        """DayTradingEngine.positions dict → 직렬화"""
        self._state["daytrading"]["positions"] = [
            {
                "code": pos.stock_code,
                "name": pos.stock_name,
                "qty": pos.qty,
                "buy_price": pos.buy_price,
                "highest_price": pos.highest_price,
            }
            for pos in positions.values()
        ]
        self._write()

    def update_swing_positions(self, positions: dict):
        """SwingEngine.positions dict → 직렬화"""
        self._state["swing"]["positions"] = [
            {
                "code": pos.code,
                "name": pos.name,
                "qty": pos.qty,
                "buy_price": pos.buy_price,
                "market": pos.market,
            }
            for pos in positions.values()
        ]
        self._write()

    def add_trade(self, trade: dict):
        """매매 이력 추가 (오늘 것만 유지)"""
        today = datetime.now().strftime("%Y-%m-%d")
        self._state["today_trades"] = [
            t for t in self._state["today_trades"]
            if t.get("date", "") == today
        ]
        trade["date"] = today
        trade["time"] = datetime.now().strftime("%H:%M:%S")
        self._state["today_trades"].append(trade)
        self._write()

    def clear(self):
        """프로세스 종료 시 호출"""
        self._state["running"] = False
        self._state["daytrading"]["active"] = False
        self._state["swing"]["active"] = False
        self._write()
