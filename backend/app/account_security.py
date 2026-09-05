from __future__ import annotations

import base64
import hashlib
import hmac
import secrets


PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1


def generate_password(length: int = 8) -> str:
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(length))


def password_hash(password: str, pepper: str) -> str:
    if not pepper:
        raise RuntimeError("APP_AUTH_SECRET is required")
    salt = secrets.token_bytes(16)
    secret_input = password.encode("utf-8") + b"\0" + pepper.encode("utf-8")
    derived = hashlib.scrypt(
        secret_input,
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=32,
    )
    return "$".join(
        (
            "scrypt-v1",
            str(SCRYPT_N),
            str(SCRYPT_R),
            str(SCRYPT_P),
            base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),
            base64.urlsafe_b64encode(derived).decode("ascii").rstrip("="),
        )
    )


def verify_password(password: str, encoded: str, pepper: str) -> bool:
    if not pepper:
        return False
    try:
        algorithm, n, r, p, salt_value, digest_value = encoded.split("$", 5)
        if algorithm != "scrypt-v1":
            return False
        salt = base64.urlsafe_b64decode(salt_value + "=" * (-len(salt_value) % 4))
        expected = base64.urlsafe_b64decode(
            digest_value + "=" * (-len(digest_value) % 4)
        )
        secret_input = password.encode("utf-8") + b"\0" + pepper.encode("utf-8")
        actual = hashlib.scrypt(
            secret_input,
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
