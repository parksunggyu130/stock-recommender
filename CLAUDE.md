# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A personal-use stock recommendation PWA for KOSPI/KOSDAQ. It screens the top-500-by-market-cap
universe daily using 1-month daily-candle technical indicators, ranks the top 10, re-ranks with
Naver news sentiment (if configured) to pick a final top 3, and sends push/Discord notifications
at 07:00 KST (recommendation) and 16:00 KST (EOD performance check + limit-up scan). See
`README.md` for the full product spec (scoring rules, precursor-stats feature, deployment options)
— it's in Korean and is the source of truth for *why* the code behaves as it does; don't duplicate
that reasoning here, just reference it.

## Commands

All backend commands run from `backend/` with the venv active.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python -m app.scripts.generate_vapid_keys   # paste output into .env

uvicorn app.main:app --reload               # run dev server (http://localhost:8000)

python -m pytest                            # run all tests
python -m pytest tests/test_simulation.py   # run a single test file
python -m pytest tests/test_simulation.py::test_virtual_portfolio_profit_calculation  # single test

.\build_exe.bat                             # rebuild the PyInstaller .exe (outputs to backend/dist/)
```

There is no separate frontend build step — `frontend/` is plain HTML/CSS/JS served directly by
FastAPI's `StaticFiles` mount (see `app/main.py`).

## Architecture

**Layering**: routers → `services.py` → (`analysis/*`, `data/*`, `notify/*`) → `models.py`/`db.py`.
Routers are thin FastAPI endpoints; nearly all business logic (compute-or-fetch-cached, save,
decide whether to notify) lives in `services.py`, which both the HTTP routers (`routers/cron.py`,
`routers/recommendations.py`, `routers/eod.py`) and the in-process scheduler (`scheduler.py`) call
into. When adding a new scheduled/cron-triggered behavior, add it to `services.py` first and wire
both a router endpoint and a scheduler job to it, following the existing `run_and_notify` /
`eod_run_and_notify` pattern.

**Two independent trigger paths for the same jobs**: `scheduler.py` (APScheduler,
`RUN_INPROCESS_SCHEDULER=true`) runs jobs in-process for anyone keeping a PC/exe running 24/7, and
`routers/cron.py` exposes `POST /api/cron/daily` / `POST /api/cron/eod` (guarded by
`X-Cron-Secret`) for external free cron services (used with free-tier cloud hosts that sleep and
can't rely on an in-process scheduler). Both paths call the exact same `services.run_and_notify` /
`services.eod_run_and_notify`, which are idempotent per-day via the `notified`/`eod_notified` flags
on `DailyRecommendation` — a job re-run mid-day or from both trigger paths won't double-notify.

**Data source**: `app/data/krx.py` calls Naver's mobile stock API (`m.stock.naver.com`) directly
via a reused `requests.Session` — no login/key needed. This deliberately replaced an earlier
`pykrx`-based implementation (see the module docstring): `pykrx`'s market-cap ranking API started
requiring KRX member login, and per-ticker `pykrx` calls had severe unexplained overhead once
packaged as a PyInstaller exe. If Naver changes its API shape, this is the file to fix; a stub
matching the same functions (`get_full_market_snapshot`, `get_universe`, `get_recent_ohlcv`,
`get_limit_up_stocks`, `get_latest_trading_date`) would be a drop-in replacement.

**Scoring pipeline** (`analysis/screener.py` + `analysis/indicators.py`): `score_stock()` computes
5 boolean technical conditions (trend alignment, RSI 50-70, recent MACD golden cross, volume
surge ≥1.5x, 20-day new high) on a per-ticker OHLCV DataFrame and sums them into a 0-5 score.
`run_daily_pipeline()` scores the whole universe, takes the top 10 by score, then blends in news
sentiment (`data/news.py`, optional — no-op if `NAVER_CLIENT_ID`/`SECRET` unset) with weights
`TECH_WEIGHT`/`NEWS_WEIGHT` from `config.py` to pick the final top 3.

**Limit-up precursor tracking** (`analysis/limitup.py`, `LimitUpEvent` model): every time a stock
hits +29.5%+ in a day, `compute_precursor()` snapshots the same 5-condition score for that day and
the 4 preceding trading days, stored as JSON on the event row. `aggregate_precursor_stats()`
aggregates across all historical events into per-offset condition-hit-rate statistics — this is
designed to get more statistically meaningful the longer the app runs, so don't "clean up" old
`LimitUpEvent` rows.

**Timezone handling**: business-day logic (what "today" means, weekend skip) always goes through
`services._kst_today()` (`Asia/Seoul`), never `datetime.date.today()` directly — the server may run
in UTC (e.g. on Render). `analysis/screener.run_daily_pipeline()`'s use of `datetime.date.today()`
for the `date` field is the one exception, tied to how `DailyRecommendation.date` rows are keyed.

**Packaging duality**: the app runs both as a normal `uvicorn app.main:app` process and as a
PyInstaller-frozen `.exe` (`run.py` is the frozen entry point). Code that resolves paths (frontend
static dir in `main.py`, `.env`/DB location via `APP_BASE_DIR` in `config.py`) branches on
`sys.frozen` / `sys._MEIPASS` to work in both modes — preserve this when touching path resolution.

**Notifications**: `services._notify()` fans out to both `notify/push.py` (Web Push via VAPID,
optional) and `notify/discord.py` (webhook, optional) — either, both, or neither can be configured;
the app must keep working with zero notification channels configured.
