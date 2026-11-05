import base64
import hashlib
import hmac
import ipaddress
import secrets
from urllib.parse import quote

from fastapi import Request, Response
from fastapi.responses import RedirectResponse
from nicegui import app, run
from starlette.middleware.base import BaseHTTPMiddleware

from prompt_manager.config import ADMIN_PASSWORD, ADMIN_USERNAME, DATA_DIR, TRUSTED_NETWORKS
from prompt_manager.db import execute, get

SECRET_FILE = DATA_DIR / "secret.key"
verified_headers: set[str] = set()


def storage_secret() -> str:
    if not SECRET_FILE.exists():
        SECRET_FILE.write_text(secrets.token_hex(32))
    return SECRET_FILE.read_text()


def hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)


def add_user(username: str, password: str) -> None:
    salt = secrets.token_bytes(16)
    execute("INSERT OR REPLACE INTO users (username, password_hash) VALUES (?, ?)",
            username, f"{salt.hex()}${hash_password(password, salt).hex()}")
    verified_headers.clear()


def delete_user(username: str) -> None:
    execute("DELETE FROM users WHERE username = ?", username)
    verified_headers.clear()


def is_admin(username: str | None) -> bool:
    return bool(ADMIN_USERNAME) and username == ADMIN_USERNAME


def user_exists(username: str | None) -> bool:
    return is_admin(username) or get("SELECT 1 FROM users WHERE username = ?", username) is not None


def verify_user(username: str, password: str) -> bool:
    if is_admin(username):
        return hmac.compare_digest(password.encode(), ADMIN_PASSWORD.encode())
    user = get("SELECT password_hash FROM users WHERE username = ?", username)
    if not user:
        return False
    salt, expected = user["password_hash"].split("$")
    return hmac.compare_digest(hash_password(password, bytes.fromhex(salt)).hex(), expected)


def verify_basic_auth(header: str) -> bool:
    if not header.startswith("Basic "):
        return False
    try:
        username, _, password = base64.b64decode(header[6:]).decode().partition(":")
    except ValueError:
        return False
    return verify_user(username, password)


async def check_basic_auth(header: str) -> bool:
    if header not in verified_headers and await run.io_bound(verify_basic_auth, header):
        verified_headers.add(header)
    return header in verified_headers


def is_trusted(request: Request) -> bool:
    try:
        ip = ipaddress.ip_address(request.client.host if request.client else "")
    except ValueError:
        return False
    return any(ip in network for network in TRUSTED_NETWORKS)


def safe_redirect(path: str) -> str:
    return path if path.startswith("/") and not path.startswith("//") else "/"


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/"):
            if not is_trusted(request) and not await check_basic_auth(request.headers.get("authorization", "")):
                return Response(status_code=401, headers={"WWW-Authenticate": "Basic"})
        elif path != "/login" and not path.startswith("/_nicegui") and not user_exists(app.storage.user.get("username")):
            app.storage.user.clear()
            return RedirectResponse(f"/login?redirect_to={quote(path)}")
        return await call_next(request)


app.add_middleware(AuthMiddleware)
