import json
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from auth.security import hash_password
from database.connection import create_database_engine
from database.models import AuditLog, Permission, Role, User, user_roles, role_permissions


def audit(db, actor_id, action, object_type=None, object_id=None, details=None):
    db.add(AuditLog(user_id=actor_id, action=action, object_type=object_type, object_id=str(object_id) if object_id is not None else None, details=json.dumps(details or {})))


def get_users(database_url):
    engine = create_database_engine(database_url)
    try:
        with Session(engine) as db:
            users = list(db.scalars(select(User).order_by(User.username)).all())
            return [{
                "id": u.id, "username": u.username, "email": u.email or "",
                "full_name": u.full_name or "", "active": u.is_active,
                "superadmin": u.is_superadmin,
                "roles": [r.name for r in u.roles],
                "role_ids": [r.id for r in u.roles],
                "created_at": u.created_at, "last_login": u.last_login,
            } for u in users]
    finally:
        engine.dispose()


def update_user(database_url, actor_id, user_id, email, full_name, is_active, is_superadmin, role_ids, new_password=""):
    engine = create_database_engine(database_url)
    try:
        with Session(engine) as db:
            user = db.get(User, user_id)
            if user is None:
                return False, "User not found."
            if user.id == actor_id and (not is_active or not is_superadmin):
                return False, "You cannot deactivate or remove superadmin status from your own account."
            if user.id == actor_id and not is_superadmin:
                return False, "You cannot remove superadmin status from your own account."
            email = email.strip()
            if email:
                duplicate = db.execute(select(User).where(User.email == email, User.id != user_id)).scalar_one_or_none()
                if duplicate:
                    return False, "Email already exists."
            user.email = email or None
            user.full_name = full_name.strip() or None
            user.is_active = bool(is_active)
            user.is_superadmin = bool(is_superadmin)
            user.roles = [] if user.is_superadmin else list(db.scalars(select(Role).where(Role.id.in_(role_ids or []))).all())
            if new_password:
                if len(new_password) < 8:
                    return False, "New password must contain at least 8 characters."
                user.password_hash = hash_password(new_password)
            audit(db, actor_id, "UPDATE_USER", "USER", user.id, {"active": user.is_active, "superadmin": user.is_superadmin, "roles": [r.name for r in user.roles], "password_changed": bool(new_password)})
            db.commit()
            return True, "User updated successfully."
    finally:
        engine.dispose()


def get_roles(database_url):
    engine = create_database_engine(database_url)
    try:
        with Session(engine) as db:
            roles = list(db.scalars(select(Role).order_by(Role.name)).all())
            return [{"id": r.id, "name": r.name, "description": r.description or "", "permissions": [p.permission_code for p in r.permissions], "permission_ids": [p.id for p in r.permissions], "user_count": len(r.users)} for r in roles]
    finally:
        engine.dispose()


def get_permissions(database_url):
    engine = create_database_engine(database_url)
    try:
        with Session(engine) as db:
            return list(db.scalars(select(Permission).order_by(Permission.permission_code)).all())
    finally:
        engine.dispose()


def save_role(database_url, actor_id, role_id, name, description, permission_ids):
    name = name.strip()
    if not name:
        return False, "Role name is required."
    engine = create_database_engine(database_url)
    try:
        with Session(engine) as db:
            role = db.get(Role, role_id) if role_id else None
            duplicate = db.execute(select(Role).where(Role.name == name, Role.id != role_id)).scalar_one_or_none()
            if duplicate:
                return False, "A role with this name already exists."
            if role is None:
                role = Role(name=name, description=description.strip() or None)
                db.add(role)
                db.flush()
                action = "CREATE_ROLE"
            else:
                role.name = name
                role.description = description.strip() or None
                action = "UPDATE_ROLE"
            role.permissions = list(db.scalars(select(Permission).where(Permission.id.in_(permission_ids or []))).all())
            audit(db, actor_id, action, "ROLE", role.id, {"name": role.name, "permissions": [p.permission_code for p in role.permissions]})
            db.commit()
            return True, "Role saved successfully."
    finally:
        engine.dispose()


def delete_role(database_url, actor_id, role_id):
    engine = create_database_engine(database_url)
    try:
        with Session(engine) as db:
            role = db.get(Role, role_id)
            if not role:
                return False, "Role not found."
            if role.users:
                return False, "This role is assigned to users. Reassign those users before deleting it."
            name = role.name
            db.delete(role)
            audit(db, actor_id, "DELETE_ROLE", "ROLE", role_id, {"name": name})
            db.commit()
            return True, "Role deleted."
    finally:
        engine.dispose()


def get_audit_logs(database_url, limit=500):
    engine = create_database_engine(database_url)
    try:
        with Session(engine) as db:
            stmt = select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(limit)
            rows = list(db.scalars(stmt).all())
            user_ids = {r.user_id for r in rows if r.user_id}
            names = {}
            if user_ids:
                names = {u.id: u.username for u in db.scalars(select(User).where(User.id.in_(user_ids))).all()}
            return [{"id": r.id, "timestamp": r.timestamp, "username": names.get(r.user_id, "System"), "action": r.action, "object_type": r.object_type or "", "object_id": r.object_id or "", "details": r.details or ""} for r in rows]
    finally:
        engine.dispose()
