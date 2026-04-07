"""
Antikythera 대시보드 서버
실행: python dashboard.py
접속: http://localhost:8765
"""
import sys
import io
import os
import signal
import json
import time
from pathlib import Path
from datetime import datetime

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

STATE_FILE = Path("trading_state.json")
LOG_FILE = Path("logs/antikythera.log")
SETTINGS_OVERRIDE_FILE = Path("settings_override.json")

app = FastAPI(title="Antikythera Dashboard")
app.mount("/static", StaticFiles(directory="static"), name="static")

# ── API 클라이언트 (lazy init) ──────────────────────────────
_kiwoom = None
_kr_invest = None

def get_kiwoom():
    global _kiwoom
    if _kiwoom is None:
        from core.api.kiwoom_api import KiwoomAPI
        _kiwoom = KiwoomAPI()
    return _kiwoom

def get_kr_invest():
    global _kr_invest
    if _kr_invest is None:
        from core.api.kr_invest_api import KRInvestAPI
        _kr_invest = KRInvestAPI()
    return _kr_invest

# ── 관심종목 스캔 캐시 (5분) ────────────────────────────────
_scan_cache: dict = {}
_scan_cache_time: float = 0
SCAN_CACHE_TTL = 300  # 5분


def read_state() -> dict:
    if not STATE_FILE.exists():
        return {"running": False, "error": "main.py가 실행되지 않았습니다"}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        return {"running": False, "error": str(e)}


def read_settings_override() -> dict:
    if SETTINGS_OVERRIDE_FILE.exists():
        try:
            return json.loads(SETTINGS_OVERRIDE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


# ── 기본 엔드포인트 ─────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    html_file = Path("static/index.html")
    if html_file.exists():
        return HTMLResponse(html_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>static/index.html 없음</h1>")


@app.get("/api/status")
async def get_status():
    return JSONResponse(read_state())


@app.get("/api/logs")
async def get_logs(lines: int = 150):
    if not LOG_FILE.exists():
        return JSONResponse({"logs": []})
    try:
        all_lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        return JSONResponse({"logs": all_lines[-lines:]})
    except Exception as e:
        return JSONResponse({"logs": [], "error": str(e)})


@app.post("/api/stop")
async def stop_main():
    state = read_state()
    pid = state.get("pid")
    if not pid:
        raise HTTPException(status_code=404, detail="main.py PID를 찾을 수 없습니다")
    if not state.get("running", False):
        raise HTTPException(status_code=400, detail="main.py가 실행 중이 아닙니다")
    try:
        if sys.platform == "win32":
            os.kill(pid, signal.CTRL_C_EVENT)
        else:
            os.kill(pid, signal.SIGTERM)
        return JSONResponse({"success": True, "message": f"종료 신호 전송 완료 (PID: {pid})"})
    except ProcessLookupError:
        raise HTTPException(status_code=404, detail=f"PID {pid} 프로세스 없음")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health")
async def health():
    return {"status": "ok", "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


# ── 차트 엔드포인트 ─────────────────────────────────────────

@app.get("/api/chart/kr/{code}")
async def kr_chart(code: str, interval: str = "5"):
    """국내 종목 분봉 차트 (lightweight-charts 형식)"""
    try:
        api = get_kiwoom()
        df = api.get_minute_chart(code, interval=interval)
        if df is None or df.empty:
            raise HTTPException(status_code=404, detail="데이터 없음")

        candles = []
        for _, row in df.iterrows():
            dt_str = str(row["Date"])  # 20260407150000
            try:
                dt = datetime.strptime(dt_str, "%Y%m%d%H%M%S")
                ts = int(dt.timestamp())
            except Exception:
                continue
            candles.append({
                "time": ts,
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(row["Volume"]),
            })

        # 기술적 지표 추가
        from core.indicators.technical import TechnicalIndicators
        ti = TechnicalIndicators("swing")
        df_ind = ti.add_all(df)
        last = df_ind.iloc[-1]

        indicators = {
            "rsi": round(float(last.get("RSI_14", 0) or 0), 2),
            "macd": round(float(last.get("MACD", 0) or 0), 2),
            "macd_hist": round(float(last.get("MACD_hist", 0) or 0), 2),
            "bb_upper": round(float(last.get("BB_upper", 0) or 0), 0),
            "bb_lower": round(float(last.get("BB_lower", 0) or 0), 0),
            "signal": ti.get_signal(df_ind),
        }
        return JSONResponse({"candles": candles, "indicators": indicators})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/chart/us/{ticker}")
async def us_chart(ticker: str, exchange: str = "NAS"):
    """미국 종목 일봉 차트 (lightweight-charts 형식)"""
    try:
        api = get_kr_invest()
        df = api.get_us_daily_chart(ticker, exchange=exchange, count=60)
        if df is None or df.empty:
            raise HTTPException(status_code=404, detail="데이터 없음")

        candles = []
        for _, row in df.iterrows():
            date_str = str(row["Date"])  # 20260406
            try:
                dt = datetime.strptime(date_str, "%Y%m%d")
                ts = int(dt.timestamp())
            except Exception:
                continue
            candles.append({
                "time": ts,
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(row["Volume"]),
            })

        from core.indicators.technical import TechnicalIndicators
        ti = TechnicalIndicators("swing")
        df_ind = ti.add_all(df)
        last = df_ind.iloc[-1]

        indicators = {
            "rsi": round(float(last.get("RSI_14", 0) or 0), 2),
            "macd": round(float(last.get("MACD", 0) or 0), 4),
            "macd_hist": round(float(last.get("MACD_hist", 0) or 0), 4),
            "bb_upper": round(float(last.get("BB_upper", 0) or 0), 2),
            "bb_lower": round(float(last.get("BB_lower", 0) or 0), 2),
            "signal": ti.get_signal(df_ind),
        }
        return JSONResponse({"candles": candles, "indicators": indicators})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 관심종목 스캔 ───────────────────────────────────────────

@app.get("/api/watchlist/scan")
async def watchlist_scan(force: bool = False):
    """관심종목 전체 스캔 (5분 캐시)"""
    global _scan_cache, _scan_cache_time

    if not force and _scan_cache and (time.time() - _scan_cache_time) < SCAN_CACHE_TTL:
        return JSONResponse({**_scan_cache, "cached": True})

    from config.settings import SWING_WATCHLIST
    from core.indicators.technical import TechnicalIndicators
    from core.strategy.swing.engine import US_EXCHANGE_MAP

    ti = TechnicalIndicators("swing")
    kiwoom = get_kiwoom()
    kr_invest = get_kr_invest()

    kr_results = []
    for stock in SWING_WATCHLIST.get("kr", []):
        code = stock.get("code", "")
        name = stock.get("name", "")
        try:
            price_info = kiwoom.get_stock_price(code)
            price = price_info["현재가"] if price_info else 0
            df = kiwoom.get_minute_chart(code, interval="60")
            signal = "HOLD"
            if df is not None and len(df) >= 20:
                df = ti.add_all(df)
                signal = ti.get_signal(df)
                last = df.iloc[-1]
                rsi = round(float(last.get("RSI_14", 0) or 0), 1)
            else:
                rsi = 0
            kr_results.append({
                "code": code, "name": name, "market": "KR",
                "price": price, "signal": signal, "rsi": rsi,
            })
            time.sleep(0.3)
        except Exception as e:
            kr_results.append({"code": code, "name": name, "market": "KR",
                                "price": 0, "signal": "ERR", "rsi": 0, "error": str(e)})

    us_results = []
    for stock in SWING_WATCHLIST.get("us", []):
        ticker = stock.get("ticker", "")
        name = stock.get("name", "")
        exchange = US_EXCHANGE_MAP.get(ticker, "NAS")
        try:
            price_info = kr_invest.get_us_stock_price(ticker, exchange)
            price = price_info["현재가"] if price_info else 0
            rate = price_info.get("등락률", 0) if price_info else 0
            df = kr_invest.get_us_daily_chart(ticker, exchange=exchange, count=60)
            signal = "HOLD"
            rsi = 0
            if df is not None and len(df) >= 20:
                df = ti.add_all(df)
                signal = ti.get_signal(df)
                last = df.iloc[-1]
                rsi = round(float(last.get("RSI_14", 0) or 0), 1)
            us_results.append({
                "code": ticker, "name": name, "market": "US",
                "price": price, "rate": rate, "signal": signal, "rsi": rsi,
            })
            time.sleep(0.3)
        except Exception as e:
            us_results.append({"code": ticker, "name": name, "market": "US",
                                "price": 0, "rate": 0, "signal": "ERR", "rsi": 0, "error": str(e)})

    _scan_cache = {
        "kr": kr_results,
        "us": us_results,
        "scanned_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "cached": False,
    }
    _scan_cache_time = time.time()
    return JSONResponse(_scan_cache)


# ── 설정 엔드포인트 ─────────────────────────────────────────

@app.get("/api/settings")
async def get_settings():
    from config.settings import RISK, DAYTRADING_FILTER, SWING_WATCHLIST, IS_PAPER_TRADING
    overrides = read_settings_override()
    return JSONResponse({
        "is_paper_trading": IS_PAPER_TRADING,
        "risk": overrides.get("RISK", RISK),
        "daytrading_filter": overrides.get("DAYTRADING_FILTER", DAYTRADING_FILTER),
        "swing_watchlist": overrides.get("SWING_WATCHLIST", SWING_WATCHLIST),
        "has_override": SETTINGS_OVERRIDE_FILE.exists(),
    })


@app.post("/api/settings")
async def save_settings(body: dict):
    """설정을 settings_override.json에 저장 (main.py 재시작 시 반영)"""
    allowed_keys = {"RISK", "DAYTRADING_FILTER", "SWING_WATCHLIST"}
    filtered = {k: v for k, v in body.items() if k in allowed_keys}
    if not filtered:
        raise HTTPException(status_code=400, detail="변경할 설정이 없습니다")

    existing = read_settings_override()
    existing.update(filtered)
    SETTINGS_OVERRIDE_FILE.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return JSONResponse({"success": True, "message": "저장 완료. main.py 재시작 시 반영됩니다."})


@app.delete("/api/settings/override")
async def delete_override():
    """settings_override.json 삭제 (기본값으로 복원)"""
    if SETTINGS_OVERRIDE_FILE.exists():
        SETTINGS_OVERRIDE_FILE.unlink()
    return JSONResponse({"success": True, "message": "기본 설정으로 복원됨"})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8765, reload=False)
