import base64
import hashlib
import os
import re
import secrets
from typing import Any, Dict, Optional
import jwt
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from app.core.config import settings

def get_encryption_key() -> bytes:
    secret = settings.GENSHIN_COOKIE_SECRET
    if not secret:
        raise RuntimeError("FATAL ERROR: GENSHIN_COOKIE_SECRET is missing in .env!")
    return hashlib.sha256(secret.encode("utf-8")).digest()

def encrypt(text: str) -> str:
    key = get_encryption_key()
    iv = os.urandom(16)
    padder = padding.PKCS7(128).padder()
    padded_data = padder.update(text.encode("utf-8")) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded_data) + encryptor.finalize()
    return f"{iv.hex()}:{ciphertext.hex()}"

def decrypt(text: str) -> str:
    try:
        parts = text.split(":")
        iv = bytes.fromhex(parts[0])
        ciphertext = bytes.fromhex(":".join(parts[1:]))
        key = get_encryption_key()
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        plaintext = unpadder.update(padded_plaintext) + unpadder.finalize()
        return plaintext.decode("utf-8")
    except Exception:
        raise ValueError("Dữ liệu Cookie đã bị hỏng hoặc Secret Key không đúng.")

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()

def create_jwt_token(payload: Dict[str, Any], expires_days: int = 365) -> str:
    import datetime
    data = payload.copy()
    data["exp"] = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=expires_days)
    return jwt.encode(data, settings.JWT_SECRET, algorithm="HS256")

def decode_jwt_token(token: str) -> Dict[str, Any]:
    return jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])

def generate_transaction_code() -> str:
    raw = secrets.token_bytes(4)
    b64 = base64.b64encode(raw).decode("ascii")
    cleaned = re.sub(r"[^A-Za-z0-9]", "", b64).upper()[:6]
    return f"ELYRIAX {cleaned}"

def generate_order_code() -> str:
    random_hex = secrets.token_hex(4).upper()[:6]
    return f"ELYRIAX-ORD-{random_hex}"

def generate_slug(text: str) -> str:
    s = str(text).lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^\w\-]+", "", s)
    s = re.sub(r"\-\-+", "-", s)
    s = re.sub(r"^-+", "", s)
    s = re.sub(r"-+$", "", s)
    return s
