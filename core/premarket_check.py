"""
사전 점검 모듈 (08:50 실행)
API 연결, 잔고, 미국장 결과, 종목 리스트를 확인하고
텔레그램으로 준비 완료 리포트를 발송합니다.
"""
from loguru import logger

from core.api.kiwoom_api import KiwoomAPI
from core.api.kr_invest_api import KRInvestAPI
from core.risk.capital_manager import CapitalManager
from core.notification.telegram_notifier import TelegramNotifier
from core.data_source.stock_lookup import StockLookup
from config.settings import SWING_WATCHLIST


# US_EXCHANGE_MAP은 swing engine에 있으므로 여기서 직접 정의
_US_EXCHANGE_MAP = {
    "ASTS": "NAS", "IRDM": "NAS", "GSAT": "NAS", "SATS": "NAS",
    "TSAT": "NAS", "PL": "NAS", "LUNR": "NAS", "RKLB": "NAS",
    "LMT": "NYS", "NOC": "NYS", "AIR": "NYS",
    "AMZN": "NAS", "AAPL": "NAS", "VSAT": "NAS",
}


class PreMarketCheck:
    def __init__(
        self,
        kiwoom_api: KiwoomAPI,
        kr_invest_api: KRInvestAPI,
        capital_mgr: CapitalManager,
        notifier: TelegramNotifier,
        stock_lookup: StockLookup,
    ):
        self.kiwoom = kiwoom_api
        self.kr_invest = kr_invest_api
        self.capital_mgr = capital_mgr
        self.notifier = notifier
        self.stock_lookup = stock_lookup

    def run(self):
        logger.info("[사전 점검] 08:50 점검 시작")
        results = []
        ok = True

        # 1. 키움 API 연결 확인
        try:
            account_info, _ = self.kiwoom.get_account_balance()
            total_asset = account_info.get("추정예탁자산", 0)
            self.capital_mgr.update_capital(total_asset)
            results.append(f"✅ 키움 연결 정상 | 예탁자산: {total_asset:,.0f}원")
            logger.info(f"[사전 점검] 키움 잔고: {total_asset:,.0f}원")
        except Exception as e:
            results.append(f"❌ 키움 연결 오류: {e}")
            ok = False
            logger.error(f"[사전 점검] 키움 오류: {e}")

        # 2. 한국투자 API 연결 확인
        try:
            test_ticker = SWING_WATCHLIST.get("us", [{}])[0].get("ticker", "AAPL")
            exchange = _US_EXCHANGE_MAP.get(test_ticker, "NAS")
            price = self.kr_invest.get_us_stock_price(test_ticker, exchange)
            if price:
                results.append(f"✅ 한국투자 연결 정상 | {test_ticker}: ${price['현재가']:.2f}")
            else:
                results.append("⚠️ 한국투자 연결 됨 (시세 없음 - 미장 종료 상태일 수 있음)")
        except Exception as e:
            results.append(f"❌ 한국투자 연결 오류: {e}")
            ok = False
            logger.error(f"[사전 점검] 한국투자 오류: {e}")

        # 3. 전일 미국장 보유종목 등락률 확인
        us_watchlist = SWING_WATCHLIST.get("us", [])
        us_movers = []
        for stock in us_watchlist[:5]:  # 상위 5개만
            try:
                ticker = stock.get("ticker", "")
                name = stock.get("name", "")
                exchange = _US_EXCHANGE_MAP.get(ticker, "NAS")
                price_info = self.kr_invest.get_us_stock_price(ticker, exchange)
                if price_info and price_info.get("등락률", 0) != 0:
                    rate = price_info["등락률"]
                    emoji = "🔺" if rate > 0 else "🔻"
                    us_movers.append(f"  {emoji} {name}({ticker}): {rate:+.2f}%")
            except Exception:
                pass
        if us_movers:
            results.append("📊 미국 주요 종목:")
            results.extend(us_movers)

        # 4. 종목 리스트 갱신
        try:
            self.stock_lookup.load(self.kiwoom.token)
            results.append("✅ 종목 리스트 갱신 완료")
        except Exception as e:
            results.append(f"⚠️ 종목 리스트 갱신 실패: {e}")

        # 5. 자금 배분 현황
        summary = self.capital_mgr.summary()
        results.append(
            f"💰 자금 현황: 단타 {summary['국내단타']} / "
            f"스윙 {summary['국내스윙']} / 해외 {summary['해외스윙']}"
        )

        # 텔레그램 발송
        status = "✅ 시스템 준비 완료" if ok else "⚠️ 일부 오류 발생 - 확인 필요"
        msg = f"🌅 [08:50 사전 점검]\n{status}\n\n" + "\n".join(results)
        self.notifier._send(msg)
        logger.info(f"[사전 점검] 완료 - {'정상' if ok else '오류 있음'}")
        return ok
