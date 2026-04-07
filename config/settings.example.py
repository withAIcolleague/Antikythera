# ============================================================
# Antikythera - 자동매매 시스템 설정 템플릿
# 이 파일을 복사해서 settings.py로 만들고 API 키를 채워넣으세요
# cp config/settings.example.py config/settings.py
# ============================================================

# ── 모의투자 여부 ──────────────────────────────────────────
IS_PAPER_TRADING = True  # True: 모의투자, False: 실전투자

# ── 키움증권 API ───────────────────────────────────────────
KIWOOM_PAPER = {           # 모의투자 키
    "api_key": "",
    "api_secret_key": "",
    "account_num": "",
}

KIWOOM_LIVE = {            # 실전투자 키
    "api_key": "",
    "api_secret_key": "",
    "account_num": "",
}

KIWOOM = KIWOOM_PAPER if IS_PAPER_TRADING else KIWOOM_LIVE

# ── 한국투자증권 API (향후 해외주식 확장용) ─────────────────
KR_INVEST_PAPER = {        # 모의투자 키
    "api_key": "",
    "api_secret_key": "",
    "account_num": "",
}

KR_INVEST_LIVE = {         # 실전투자 키
    "api_key": "",
    "api_secret_key": "",
    "account_num": "",
}

KR_INVEST = KR_INVEST_PAPER if IS_PAPER_TRADING else KR_INVEST_LIVE

# ── 텔레그램 알림 ──────────────────────────────────────────
TELEGRAM = {
    "enabled": True,
    "bot_token": "",   # 텔레그램 봇 토큰
    "chat_id": "",     # 알림 받을 채팅 ID
}

# ── 총 운용 자금 설정 (원 단위) ─────────────────────────────
TOTAL_CAPITAL = 10_000_000  # 총 운용금액

# ── 운용금액별 자금 비중 설정 ──────────────────────────────
CAPITAL_ALLOCATION_PAPER = {   # 모의투자 기준
    "tier1": {  # ~1억
        "threshold": 100_000_000,
        "kr_daytrading": 0.50,
        "kr_swing": 0.30,
        "us_swing": 0.10,
        "cash_buffer": 0.10,
    },
    "tier2": {  # 1억 ~ 5억
        "threshold": 500_000_000,
        "kr_daytrading": 0.35,
        "kr_swing": 0.30,
        "us_swing": 0.25,
        "cash_buffer": 0.10,
    },
    "tier3": {  # 5억 이상
        "threshold": float("inf"),
        "kr_daytrading": 0.25,
        "kr_swing": 0.30,
        "us_swing": 0.35,
        "cash_buffer": 0.10,
    },
}

CAPITAL_ALLOCATION_LIVE = {    # 실전투자 기준
    "tier1": {  # ~1,000만원
        "threshold": 10_000_000,
        "kr_daytrading": 0.50,
        "kr_swing": 0.30,
        "us_swing": 0.10,
        "cash_buffer": 0.10,
    },
    "tier2": {  # 1,000만원 ~ 5,000만원
        "threshold": 50_000_000,
        "kr_daytrading": 0.35,
        "kr_swing": 0.30,
        "us_swing": 0.25,
        "cash_buffer": 0.10,
    },
    "tier3": {  # 5,000만원 이상
        "threshold": float("inf"),
        "kr_daytrading": 0.25,
        "kr_swing": 0.30,
        "us_swing": 0.35,
        "cash_buffer": 0.10,
    },
}

CAPITAL_ALLOCATION = CAPITAL_ALLOCATION_PAPER if IS_PAPER_TRADING else CAPITAL_ALLOCATION_LIVE

# ── 종목당 최대 투자 비중 ──────────────────────────────────
MAX_POSITION_RATIO = {
    "daytrading": 0.08,
    "swing": 0.12,
}

# ── 리스크 관리 ────────────────────────────────────────────
RISK = {
    "stop_loss_pct": 3.0,
    "trailing_stop_pct": 5.0,
    "daily_loss_limit_pct": 5.0,
}

# ── 기술적 지표 파라미터 ───────────────────────────────────
INDICATORS = {
    "daytrading": {
        "rsi_period": 14,
        "rsi_overbought": 70,
        "rsi_oversold": 30,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "bb_period": 20,
        "bb_std": 2,
    },
    "swing": {
        "rsi_period": 14,
        "rsi_overbought": 65,
        "rsi_oversold": 35,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "bb_period": 20,
        "bb_std": 2,
    },
}

# ── 공시/뉴스 모니터링 ─────────────────────────────────────
DATA_SOURCE = {
    "krx_kind_url": "https://kind.krx.co.kr",
    "dart_api_key": "",
    "naver_news_enabled": True,
    "disclosure_interval_sec": 30,
    "news_interval_sec": 300,
}

# ── 단타 - 공시 자동 도출 필터 ────────────────────────────
DAYTRADING_FILTER = {
    "min_market_cap": 50_000_000_000,
    "min_volume": 100_000,
    "exclude_types": ["관리종목", "투자경고", "투자위험", "정리매매"],
    "max_positions": 5,
}

# ── 스윙 - 관심종목 수동 등록 ─────────────────────────────
SWING_WATCHLIST = {
    "kr": [
        # {"code": "005930", "name": "삼성전자"},
    ],
    "us": [
        # {"ticker": "AAPL", "name": "Apple"},
    ],
}
