from datetime import datetime
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from auth.security import hash_password, verify_password
from database.connection import create_database_engine
from database.models import AuditLog, Permission, Role, User

DEFAULT_PERMISSIONS = {
    "VIEW_DATA": "View datasets and results",
    "IMPORT_DATA": "Import geophysical data",
    "EDIT_DATA": "Edit geophysical data",
    "DELETE_DATA": "Delete geophysical data",
    "PROCESS_MAGNETIC": "Run magnetic processing",
    "PROCESS_GRAVITY": "Run gravity processing",
    "CREATE_CONTOURS": "Create contour maps",
    "RUN_TARGETING": "Run normalization, weighting, confidence and concordance",
    "CREATE_REPORT": "Create reports",
    "EXPORT_DATA": "Export data and results",
    "MANAGE_PROJECTS": "Create and manage projects",
    "MANAGE_TABLES": "Create and manage application tables",
    "MANAGE_USERS": "Create and manage users",
    "MANAGE_ROLES": "Create roles and assign permissions",
    "MANAGE_DATABASE": "Manage database connections",
    "VIEW_AUDIT_LOG": "View audit history",
}

DEFAULT_ROLES = {
    "Viewer": ["VIEW_DATA"],
    "Data Analyst": ["VIEW_DATA", "IMPORT_DATA", "EXPORT_DATA"],
    "Geophysicist": [
        "VIEW_DATA", "IMPORT_DATA", "EDIT_DATA", "PROCESS_MAGNETIC",
        "PROCESS_GRAVITY", "CREATE_CONTOURS", "RUN_TARGETING",
        "CREATE_REPORT", "EXPORT_DATA",
    ],
    "Project Administrator": [
        "VIEW_DATA", "IMPORT_DATA", "EDIT_DATA", "DELETE_DATA",
        "PROCESS_MAGNETIC", "PROCESS_GRAVITY", "CREATE_CONTOURS",
        "RUN_TARGETING", "CREATE_REPORT", "EXPORT_DATA", "MANAGE_PROJECTS",
        "MANAGE_TABLES",
    ],
}


def initialize_security_data(database_url: str) -> None:
    engine = create_database_engine(database_url)
    try:
        with Session(engine) as db:
            permissions = {}
            for code, description in DEFAULT_PERMISSIONS.items():
                item = db.execute(select(Permission).where(Permission.permission_code == code)).scalar_one_or_none()
                if item is None:
                    item = Permission(permission_code=code, description=description)
                    db.add(item)
                    db.flush()
                elif not item.description:
                    item.description = description
                permissions[code] = item

            for role_name, codes in DEFAULT_ROLES.items():
                role = db.execute(select(Role).where(Role.name == role_name)).scalar_one_or_none()
                if role is None:
                    role = Role(name=role_name, description=f"Default {role_name} role")
                    db.add(role)
                    db.flush()
                role.permissions = [permissions[c] for c in codes]
            db.commit()
    finally:
        engine.dispose()


def create_user(database_url: str, username: str, password: str, email: str = "", full_name: str = "", is_superadmin: bool = False, role_ids: list[int] | None = None) -> tuple[bool, str]:
    username = username.strip()
    email = email.strip()
    if len(username) < 3:
        return False, "Username must contain at least 3 characters."
    if len(password) < 8:
        return False, "Password must contain at least 8 characters."

    engine = create_database_engine(database_url)
    try:
        with Session(engine) as db:
            if db.execute(select(User).where(User.username == username)).scalar_one_or_none():
                return False, "Username already exists."
            if email and db.execute(select(User).where(User.email == email)).scalar_one_or_none():
                return False, "Email already exists."
            user = User(
                username=username,
                password_hash=hash_password(password),
                email=email or None,
                full_name=full_name.strip() or None,
                is_superadmin=is_superadmin,
            )
            if role_ids and not is_superadmin:
                user.roles = list(db.scalars(select(Role).where(Role.id.in_(role_ids))).all())
            db.add(user)
            db.flush()
            db.add(AuditLog(user_id=user.id, action="CREATE_USER", object_type="USER", object_id=str(user.id), details=json.dumps({"username": username, "superadmin": is_superadmin})))
            db.commit()
        return True, "User created successfully."
    finally:
        engine.dispose()


def authenticate_user(database_url: str, username: str, password: str):
    engine = create_database_engine(database_url)
    try:
        with Session(engine) as db:
            user = db.execute(select(User).where(User.username == username.strip())).scalar_one_or_none()
            if user is None or not user.is_active or not verify_password(password, user.password_hash):
                return None
            user.last_login = datetime.utcnow()
            db.add(AuditLog(user_id=user.id, action="LOGIN", object_type="USER", object_id=str(user.id), details="Successful login"))
            db.commit()
            return {"id": user.id, "username": user.username, "full_name": user.full_name, "is_superadmin": user.is_superadmin}
    finally:
        engine.dispose()


def user_has_permission(database_url: str, user_id: int, permission_code: str) -> bool:
    engine = create_database_engine(database_url)
    try:
        with Session(engine) as db:
            user = db.get(User, user_id)
            if user is None or not user.is_active:
                return False
            if user.is_superadmin:
                return True
            return any(p.permission_code == permission_code for role in user.roles for p in role.permissions)
    finally:
        engine.dispose()


def get_user_permissions(database_url: str, user_id: int) -> set[str]:
    engine = create_database_engine(database_url)
    try:
        with Session(engine) as db:
            user = db.get(User, user_id)
            if user is None or not user.is_active:
                return set()
            if user.is_superadmin:
                return set(DEFAULT_PERMISSIONS)
            return {p.permission_code for role in user.roles for p in role.permissions}
    finally:
        engine.dispose()
