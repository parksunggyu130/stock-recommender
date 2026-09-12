@echo off
REM 주식 추천 앱 실행 파일(.exe) 빌드 스크립트
REM backend 폴더에서 실행하세요: build_exe.bat
cd /d %~dp0

if not exist .venv (
    echo 먼저 가상환경을 만들고 requirements.txt를 설치하세요 (README 참고).
    exit /b 1
)

call .venv\Scripts\activate.bat
pip install --quiet pyinstaller

pyinstaller --noconfirm --clean ^
  --name StockRecommender ^
  --add-data "..\frontend;frontend" ^
  --collect-all pywebpush ^
  --collect-all py_vapid ^
  --hidden-import apscheduler.triggers.cron ^
  --hidden-import apscheduler.executors.pool ^
  --hidden-import apscheduler.jobstores.memory ^
  run.py

echo.
echo 빌드 완료: dist\StockRecommender\StockRecommender.exe
echo 이 폴더(dist\StockRecommender)를 통째로 옮겨서 사용하세요.
