from __future__ import annotations

import base64
import hashlib
import secrets

from cryptography.fernet import Fernet


PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"


def generate_password() -> str:
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(8))


def password_hash(password: str, pepper: str) -> str:
    if not pepper:
        raise RuntimeError("APP_AUTH_SECRET is required")
    salt = secrets.token_bytes(16)
    secret_input = password.encode("utf-8") + b"\0" + pepper.encode("utf-8")
    derived = hashlib.scrypt(secret_input, salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "$".join(
        (
            "scrypt-v1", "16384", "8", "1",
            base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),
            base64.urlsafe_b64encode(derived).decode("ascii").rstrip("="),
        )
    )


def encrypt_password(password: str, secret: str) -> str:
    if not secret:
        raise RuntimeError("APP_AUTH_SECRET is required")
    digest = hashlib.sha256(("account-password-v1\0" + secret).encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest)).encrypt(password.encode("utf-8")).decode("ascii")
