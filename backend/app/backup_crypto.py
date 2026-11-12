"""Password encryption for backup copies that leave this computer, and safe local storage of that password.

File format (JSON, so it is recognisable; the backup itself is unreadable without the password):
    {"app": "Analytivest", "encrypted": 1, "cipher": "AES-256-GCM",
     "kdf": {"name": "scrypt", "n": 131072, "r": 8, "p": 1, "salt": "<base64>"},
     "nonce": "<base64>", "ciphertext": "<base64>"}
The key is derived from the password with scrypt (memory-hard, slows down guessing). AES-GCM detects any
tampering or a wrong password. The KDF parameters are stored in the file, so they can be raised later
without breaking old backups.

The password is needed again for every weekly backup, so it is kept on this computer encrypted with Windows
DPAPI (tied to your Windows account): other Windows users, and anyone who copies the database to another
PC, cannot recover it. It is never written to backups.
"""
from __future__ import annotations

import base64
import json
import os
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

AAD = b"Analytivest backup v1"
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 17, 8, 1  # ~1 s and 128 MB per derivation
MAX_SCRYPT_N = 2 ** 20  # refuse files that would make us burn excessive memory
MIN_PASSWORD_LEN = 10


class WrongPassword(Exception):
    pass


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(password.encode("utf-8"))


def encrypt(plain: bytes, password: str) -> bytes:
    salt, nonce = os.urandom(16), os.urandom(12)
    key = _derive(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    ct = AESGCM(key).encrypt(nonce, plain, AAD)
    env = {"app": "Analytivest", "encrypted": 1, "cipher": "AES-256-GCM",
           "kdf": {"name": "scrypt", "n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P, "salt": _b64(salt)},
           "nonce": _b64(nonce), "ciphertext": _b64(ct)}
    return json.dumps(env, separators=(",", ":")).encode("ascii")


def envelope(data: bytes) -> dict[str, Any] | None:
    """The parsed envelope if `data` is an encrypted backup, else None."""
    if not data.lstrip().startswith(b"{") or b'"encrypted"' not in data[:200]:
        return None
    try:
        env = json.loads(data)
    except ValueError:
        return None
    return env if isinstance(env, dict) and env.get("app") == "Analytivest" and env.get("encrypted") == 1 else None


def decrypt(env: dict[str, Any], password: str) -> bytes:
    try:
        kdf = env["kdf"]
        n, r, p = int(kdf["n"]), int(kdf["r"]), int(kdf["p"])
        salt, nonce, ct = (base64.b64decode(x, validate=True) for x in (kdf["salt"], env["nonce"], env["ciphertext"]))
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError("The encrypted backup is damaged.") from e
    if kdf.get("name") != "scrypt" or env.get("cipher") != "AES-256-GCM" or not (2 <= n <= MAX_SCRYPT_N) \
            or n & (n - 1) or not (1 <= r <= 32 and 1 <= p <= 16) or len(nonce) != 12:
        raise ValueError("Unsupported encrypted backup format.")
    try:
        return AESGCM(_derive(password, salt, n, r, p)).decrypt(nonce, ct, AAD)
    except InvalidTag as e:
        raise WrongPassword("Wrong password (or the file was modified).") from e


# ---------------- local password storage (Windows DPAPI) ----------------
_ENTROPY = b"Analytivest backup password"


def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(b: bytes):
        buf = ctypes.create_string_buffer(b, len(b))
        return Blob(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    inp, _keep1 = blob(data)
    ent, _keep2 = blob(_ENTROPY)
    out = Blob()
    flags = 0x1  # CRYPTPROTECT_UI_FORBIDDEN
    ok = (crypt32.CryptProtectData(ctypes.byref(inp), ctypes.c_wchar_p("Analytivest"), ctypes.byref(ent), None, None,
                                   flags, ctypes.byref(out)) if protect else
          crypt32.CryptUnprotectData(ctypes.byref(inp), None, ctypes.byref(ent), None, None, flags, ctypes.byref(out)))
    if not ok:
        raise OSError(ctypes.GetLastError(), "Windows could not protect/unprotect the saved password")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def can_store_password() -> bool:
    return os.name == "nt"


def seal(password: str) -> str:
    """Password -> string safe to keep in the local database (only this Windows account can open it)."""
    if not can_store_password():
        raise OSError("Saving the backup password needs Windows (DPAPI).")
    return _b64(_dpapi(password.encode("utf-8"), True))


def unseal(sealed: str) -> str:
    return _dpapi(base64.b64decode(sealed), False).decode("utf-8")
