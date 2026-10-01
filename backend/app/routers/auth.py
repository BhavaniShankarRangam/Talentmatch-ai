from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.db import get_db
from app.deps import PERMISSIONS, get_current_user
from app.models import Tenant, User
from app.security import create_access_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str


def user_out(user: User, tenant: Tenant) -> dict:
    return {
        "id": user.id, "email": user.email, "full_name": user.full_name, "role": user.role,
        "tenant": {"id": tenant.id, "name": tenant.name, "slug": tenant.slug},
        "permissions": sorted(p for p, roles in PERMISSIONS.items() if user.role in roles),
    }


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.strip().lower()))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    tenant = db.get(Tenant, user.tenant_id)
    audit.record(db, tenant_id=tenant.id, user=user, action="auth.login", entity_type="user", entity_id=user.id)
    db.commit()
    return {"access_token": create_access_token(user.id, tenant.id, user.role), "token_type": "bearer",
            "user": user_out(user, tenant)}


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return user_out(user, db.get(Tenant, user.tenant_id))
