"""Authentication, role-based permissions and tenant-scoped lookups."""
from typing import TypeVar

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Role, User
from app.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)

A, R, H = Role.ADMIN, Role.RECRUITER, Role.HIRING_MANAGER

PERMISSIONS: dict[str, set[str]] = {
    "jobs:read": {A, R, H},
    "jobs:write": {A, R},
    "rubric:approve": {A, R},
    "applications:read": {A, R, H},
    "applications:upload": {A, R},
    "applications:reprocess": {A, R},
    "documents:read": {A, R, H},
    "shortlist:send": {A, R},
    "integrations:read": {A, R},
    "integrations:sync": {A, R},
    "settings:write": {A},
    "audit:read": {A},
    "data:delete": {A},
    "chat:use": {A, R, H},
}


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if creds is None or not creds.credentials:
        raise unauthorized
    try:
        payload = decode_access_token(creds.credentials)
    except jwt.PyJWTError:
        raise unauthorized
    user = db.get(User, payload.get("sub"))
    if user is None or not user.is_active or user.tenant_id != payload.get("tid"):
        raise unauthorized
    return user


def require(permission: str):
    allowed = PERMISSIONS[permission]

    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=403, detail=f"Your role cannot perform '{permission}'.")
        return user

    return dependency


def can(user: User, permission: str) -> bool:
    return user.role in PERMISSIONS[permission]


T = TypeVar("T")


def get_scoped_or_404(db: Session, model: type[T], obj_id: str, tenant_id: str) -> T:
    """Fetch a tenant-owned row. Rows from other tenants return 404 so existence is not leaked."""
    obj = db.get(model, obj_id)
    if obj is None or getattr(obj, "tenant_id", None) != tenant_id:
        raise HTTPException(status_code=404, detail=f"{model.__name__} not found")
    return obj
