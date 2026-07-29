"""Authentication endpoints — FR-M-01, FR-M-10, FR-M-11."""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User, UserStatus
from app.models.exception import AuditLog
from app.config import get_settings
import uuid

settings = get_settings()
router = APIRouter()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class Token(BaseModel):
    access_token: str
    token_type: str
    user_id: str
    username: str
    role: str


class TokenData(BaseModel):
    user_id: Optional[str] = None
    username: Optional[str] = None
    role: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """FastAPI dependency — validates JWT and returns the User object."""
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exc
    except JWTError:
        raise credentials_exc

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or user.status != UserStatus.ACTIVE:
        raise credentials_exc
    return user


async def write_audit(db: AsyncSession, actor_id: str, action: str,
                      source_ip: str = None, detail: dict = None):
    """Write an audit log entry — NFR-AU-01."""
    import json
    entry = AuditLog(
        id=str(uuid.uuid4()),
        actor_type="USER",
        actor_id=actor_id,
        source_ip=source_ip,
        action=action,
        detail=detail,
    )
    db.add(entry)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/token", response_model=Token)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """
    Login and receive a JWT. FR-M-01, FR-M-11.
    Failed logins are counted and logged.
    """
    result = await db.execute(select(User).where(User.username == form_data.username))
    user = result.scalar_one_or_none()

    source_ip = request.client.host if request.client else "unknown"

    if not user or not verify_password(form_data.password, user.hashed_password):
        if user:
            # Increment failed login counter — FR-M-11
            failed = int(user.failed_logins or 0) + 1
            await db.execute(
                update(User).where(User.id == user.id)
                .values(failed_logins=str(failed),
                        status=UserStatus.LOCKED if failed >= 5 else user.status)
            )
        await write_audit(db, form_data.username, "LOGIN_FAILED",
                          source_ip, {"reason": "bad_credentials"})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    if user.status == UserStatus.LOCKED:
        raise HTTPException(status_code=403, detail="Account locked — contact administrator")

    if user.status == UserStatus.SUSPENDED:
        raise HTTPException(status_code=403, detail="Account suspended")

    # Reset failed counter, update last login
    await db.execute(
        update(User).where(User.id == user.id)
        .values(failed_logins="0", last_login=datetime.now(timezone.utc))
    )
    await write_audit(db, user.id, "LOGIN_SUCCESS", source_ip, {"role": user.role})

    token = create_access_token({"sub": user.id, "username": user.username, "role": user.role})
    return Token(
        access_token=token,
        token_type="bearer",
        user_id=user.id,
        username=user.username,
        role=user.role,
    )


@router.post("/logout")
async def logout(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Logout — audit logged. Token invalidation is client-side for this MVP."""
    await write_audit(db, current_user.id, "LOGOUT",
                      request.client.host if request.client else "unknown")
    return {"message": "Logged out"}


@router.get("/me")
async def me(current_user: User = Depends(get_current_user)):
    """Return the current user's profile."""
    return {
        "id": current_user.id,
        "username": current_user.username,
        "full_name": current_user.full_name,
        "role": current_user.role,
        "email": current_user.email,
        "client_id": current_user.client_id,
    }
