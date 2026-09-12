"""실행 파일(.exe) 진입점.

더블클릭으로 실행하면:
1) exe와 같은 폴더에 .env가 없으면 VAPID 키/크론 시크릿을 자동 생성해 새로 만들고
2) 로컬 서버를 띄운 뒤
3) 기본 브라우저로 자동 접속한다.

DB(data.db)와 .env는 항상 exe가 있는 폴더에 생성/보관되므로, 실행 파일을 다른 폴더로
옮기면 새 설정으로 다시 시작한다(파일을 통째로 같이 옮기면 데이터도 유지된다).
"""
from __future__ import annotations

import base64
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _generate_vapid_keys() -> tuple[str, str]:
    from cryptography.hazmat.primitives.asymmetric import ec

    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()
    numbers = public_key.public_numbers()
    public_bytes = b"\x04" + numbers.x.to_bytes(32, "big") + numbers.y.to_bytes(32, "big")
    private_bytes = private_key.private_numbers().private_value.to_bytes(32, "big")
    return _b64url(public_bytes), _b64url(private_bytes)


def _ensure_env_file(base_dir: Path) -> None:
    env_path = base_dir / ".env"
    if env_path.exists():
        return

    public_key, private_key = _generate_vapid_keys()
    cron_secret = _b64url(os.urandom(24))

    env_path.write_text(
        "UNIVERSE_SIZE=500\n"
        "NAVER_CLIENT_ID=\n"
        "NAVER_CLIENT_SECRET=\n"
        f"VAPID_PUBLIC_KEY={public_key}\n"
        f"VAPID_PRIVATE_KEY={private_key}\n"
        "VAPID_CONTACT_EMAIL=mailto:example@example.com\n"
        "DISCORD_WEBHOOK_URL=\n"
        f"CRON_SECRET={cron_secret}\n"
        "RUN_INPROCESS_SCHEDULER=true\n",
        encoding="utf-8",
    )
    print(f"[최초 실행] 설정 파일을 새로 만들었습니다: {env_path}")
    print("           (선택) 뉴스 추천 사유를 보려면 이 파일의 NAVER_CLIENT_ID/SECRET을 채워주세요.")
    print("           (선택, 추천) 휴대폰 알림은 DISCORD_WEBHOOK_URL을 채우는 게 가장 간단합니다.")


def _lan_ip() -> str | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def main() -> None:
    base_dir = _base_dir()
    os.environ["APP_BASE_DIR"] = str(base_dir)
    _ensure_env_file(base_dir)

    import uvicorn

    from app.main import app  # noqa: E402 (APP_BASE_DIR 설정 이후에 import 해야 함)

    port = int(os.environ.get("PORT", "8000"))

    def _open_browser() -> None:
        time.sleep(1.5)
        webbrowser.open(f"http://127.0.0.1:{port}")

    threading.Thread(target=_open_browser, daemon=True).start()

    lan_ip = _lan_ip()

    print("=" * 60)
    print(" 주식 추천 앱 서버를 시작합니다.")
    print(f" 이 PC에서: http://127.0.0.1:{port}")
    if lan_ip:
        print(f" 같은 Wi-Fi의 휴대폰에서: http://{lan_ip}:{port}")
        print("   (Windows 방화벽이 처음 접속을 물어보면 '허용'을 눌러주세요)")
        print("   ※ http(비보안)라 이 방식으로는 알림(푸시)까지는 못 받습니다.")
        print("     휴대폰 알림까지 받으려면 README의 '무료 클라우드 배포'를 참고하세요.")
    print(" 이 창을 닫으면 서버가 종료됩니다.")
    print("=" * 60)

    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
