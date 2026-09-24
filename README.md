# data branch

이 브랜치는 GitHub Actions 워크플로(`.github/workflows/daily.yml`, `eod.yml`)가
`backend/data.db`를 실행할 때마다 자동으로 커밋해 영구 보관하는 용도입니다.

- `main` 브랜치(앱 코드)와는 별개이며, 여기 푸시되어도 Render 자동 배포는 트리거되지 않습니다.
- 사람이 직접 수정하지 마세요 — 다음 워크플로 실행 시 덮어써집니다.
