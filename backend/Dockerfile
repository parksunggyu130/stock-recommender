# 프로젝트 루트(주식추천앱/)에서 빌드하세요:
#   docker build -f backend/Dockerfile -t stock-recommender .
FROM python:3.11-slim

WORKDIR /srv/backend

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY frontend /srv/frontend

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# Render 등은 PORT 환경변수를 주입하므로 셸 형태로 실행해 $PORT를 치환한다.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
