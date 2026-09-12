"""웹 푸시(VAPID) 키 쌍을 생성한다.

사용법 (backend 디렉터리에서):
    python -m app.scripts.generate_vapid_keys

출력되는 두 값을 .env 의 VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY 에 각각 넣으세요.
"""
import base64

from cryptography.hazmat.primitives.asymmetric import ec


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def main() -> None:
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()

    numbers = public_key.public_numbers()
    public_bytes = b"\x04" + numbers.x.to_bytes(32, "big") + numbers.y.to_bytes(32, "big")
    private_bytes = private_key.private_numbers().private_value.to_bytes(32, "big")

    print("VAPID_PUBLIC_KEY=" + _b64url(public_bytes))
    print("VAPID_PRIVATE_KEY=" + _b64url(private_bytes))


if __name__ == "__main__":
    main()
