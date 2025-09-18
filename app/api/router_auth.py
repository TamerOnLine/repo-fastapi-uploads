# app/api/router_auth.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel

from app.core.config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])

# ---------- Models ----------
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class User(BaseModel):
    username: str
    is_authenticated: bool = False

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# ---------- Fake user store (replace with DB) ----------
_FAKE_USERS = {
    # bcrypt hash for "admin123" (example)
    # generate with: from passlib.hash import bcrypt; print(bcrypt.hash("admin123"))
    "admin": "$2b$12$Zb0wr7oQeQH2v7ZfTQKXUOvb3k8mQ2b4Z8x2pN4yW7sTzI3m8i0mS"
}

def _verify_password(plain: str, hashed: str) -> bool:
    try:
        from passlib.hash import bcrypt
        return bcrypt.verify(plain, hashed)
    except Exception:
        # demo fallback: do NOT use in production
        return plain == "admin123"

# ---------- Key loading ----------
def _load_sign_keys():
    """
    Returns (signing_key, verify_key, alg).
    - HS*  -> use settings.JWT_SECRET for both sign & verify
    - RS*/ES* -> read private/public key files
    """
    st = get_settings()
    alg = st.JWT_ALGORITHM.upper().strip()

    if alg.startswith("HS"):
        if not st.JWT_SECRET:
            raise RuntimeError("APP_JWT_SECRET is required for HS* algorithms")
        return st.JWT_SECRET, st.JWT_SECRET, alg

    # Asymmetric: RS*, ES*
    if not st.JWT_PRIVATE_KEY_PATH or not st.JWT_PUBLIC_KEY_PATH:
        raise RuntimeError("APP_JWT_PRIVATE_KEY_PATH and APP_JWT_PUBLIC_KEY_PATH are required for RS*/ES* algorithms")

    priv = Path(st.JWT_PRIVATE_KEY_PATH).read_text(encoding="utf-8")
    pub = Path(st.JWT_PUBLIC_KEY_PATH).read_text(encoding="utf-8")
    return priv, pub, alg

def _create_access_token(subject: str, expires_minutes: Optional[int] = None) -> str:
    st = get_settings()
    sign_key, _, alg = _load_sign_keys()
    exp_min = expires_minutes or st.JWT_EXPIRE_MINUTES

    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=exp_min)).timestamp()),
    }
    return jwt.encode(payload, sign_key, algorithm=alg)

def _decode_token(token: str) -> dict:
    _, verify_key, alg = _load_sign_keys()
    try:
        return jwt.decode(token, verify_key, algorithms=[alg])
    except JWTError as e:
        # includes ExpiredSignatureError, JWK errors, etc.
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    data = _decode_token(token)
    username = data.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token payload (missing 'sub')")
    return User(username=username, is_authenticated=True)

# ---------- Endpoints ----------
@router.get("/ping")
def ping():
    return {"ok": True, "service": "auth"}

@router.post("/login", response_model=TokenResponse)
def login(form: OAuth2PasswordRequestForm = Depends()):
    """
    OAuth2 Password flow:
    Send as x-www-form-urlencoded:
      username=...&password=...
    """
    username = form.username
    password = form.password

    # TODO: replace with DB lookup
    hashed = _FAKE_USERS.get(username)
    if not hashed or not _verify_password(password, hashed):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = _create_access_token(username)
    return TokenResponse(access_token=token)

@router.get("/me", response_model=User)
def me(user: User = Depends(get_current_user)):
    return user
