"""
자금 비중 관리 모듈
총 운용금액 기준으로 단타/스윙/국내/해외 자금을 자동 배분합니다.
"""
from config.settings import TOTAL_CAPITAL, CAPITAL_ALLOCATION, MAX_POSITION_RATIO


class CapitalManager:
    def __init__(self, total_capital: float = TOTAL_CAPITAL):
        self.total_capital = total_capital
        self._allocation = self._get_allocation()

    def _get_allocation(self) -> dict:
        """운용금액 구간에 맞는 비중 반환"""
        for tier_name, tier in CAPITAL_ALLOCATION.items():
            if self.total_capital <= tier["threshold"]:
                return tier
        return list(CAPITAL_ALLOCATION.values())[-1]

    def update_capital(self, total_capital: float):
        """운용금액 갱신 (계좌 조회 후 호출)"""
        self.total_capital = total_capital
        self._allocation = self._get_allocation()

    def get_budget(self, trade_type: str) -> float:
        """
        trade_type: 'kr_daytrading' | 'kr_swing' | 'us_swing'
        반환: 해당 전략에 배정된 예산 (원)
        """
        ratio = self._allocation.get(trade_type, 0)
        return self.total_capital * ratio

    def get_max_position_size(self, trade_type: str, price: float) -> int:
        """
        종목당 최대 매수 수량 계산
        trade_type: 'daytrading' | 'swing'
        price: 현재가
        반환: 최대 매수 수량 (주)
        """
        ratio = MAX_POSITION_RATIO.get(trade_type, 0.08)
        max_amount = self.total_capital * ratio
        if price <= 0:
            return 0
        return int(max_amount / price)

    def summary(self) -> dict:
        """현재 자금 배분 현황 요약"""
        return {
            "총운용금액": f"{self.total_capital:,.0f}원",
            "국내단타": f"{self.get_budget('kr_daytrading'):,.0f}원",
            "국내스윙": f"{self.get_budget('kr_swing'):,.0f}원",
            "해외스윙": f"{self.get_budget('us_swing'):,.0f}원",
            "현금버퍼": f"{self.total_capital * self._allocation.get('cash_buffer', 0.1):,.0f}원",
        }


if __name__ == "__main__":
    cm = CapitalManager(total_capital=8_000_000)
    print(cm.summary())
    print(f"삼성전자(75,000원) 단타 최대 수량: {cm.get_max_position_size('daytrading', 75000)}주")
