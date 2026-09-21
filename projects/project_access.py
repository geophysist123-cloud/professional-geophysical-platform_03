import json
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from database.connection import create_database_engine
from database.models import AuditLog, Project, ProjectUser, Role, User


def _audit(db, user_id, action, object_type, object_id, details):
    db.add(AuditLog(user_id=user_id, action=action, object_type=object_type, object_id=str(object_id), details=json.dumps(details)))


def list_projects(database_url: str):
    engine = create_database_engine(database_url)
    try:
        with Session(engine) as db:
            return list(db.scalars(select(Project).order_by(Project.name)).all())
    finally:
        engine.dispose()


def create_project(database_url: str, actor_id: int, name: str, description: str = "", country: str = "", region: str = "", crs_epsg: int | None = None):
    name = name.strip()
    if not name:
        return False, "Project name is required."
    engine = create_database_engine(database_url)
    try:
        with Session(engine) as db:
            project = Project(name=name, description=description.strip() or None, country=country.strip() or None, region=region.strip() or None, crs_epsg=crs_epsg)
            db.add(project)
            db.flush()
            _audit(db, actor_id, "CREATE_PROJECT", "PROJECT", project.id, {"name": name})
            db.commit()
            return True, f"Project '{name}' created."
    finally:
        engine.dispose()


def list_users(database_url: str, include_inactive: bool = True):
    engine = create_database_engine(database_url)
    try:
        with Session(engine) as db:
            stmt = select(User).order_by(User.username)
            if not include_inactive:
                stmt = stmt.where(User.is_active.is_(True))
            return list(db.scalars(stmt).all())
    finally:
        engine.dispose()


def list_roles(database_url: str):
    engine = create_database_engine(database_url)
    try:
        with Session(engine) as db:
            return list(db.scalars(select(Role).order_by(Role.name)).all())
    finally:
        engine.dispose()


def assign_project_member(database_url: str, actor_id: int, project_id: int, user_id: int, role_id: int | None = None):
    engine = create_database_engine(database_url)
    try:
        with Session(engine) as db:
            project = db.get(Project, project_id)
            user = db.get(User, user_id)
            if not project or not user:
                return False, "Project or user not found."
            membership = db.execute(select(ProjectUser).where(ProjectUser.project_id == project_id, ProjectUser.user_id == user_id)).scalar_one_or_none()
            if membership is None:
                membership = ProjectUser(project_id=project_id, user_id=user_id, role_id=role_id)
                db.add(membership)
                action = "ADD_PROJECT_MEMBER"
            else:
                membership.role_id = role_id
                action = "UPDATE_PROJECT_MEMBER"
            _audit(db, actor_id, action, "PROJECT_USER", membership.id if membership.id else f"{project_id}:{user_id}", {"project_id": project_id, "user_id": user_id, "role_id": role_id})
            db.commit()
            return True, "Project access saved."
    finally:
        engine.dispose()


def remove_project_member(database_url: str, actor_id: int, project_user_id: int):
    engine = create_database_engine(database_url)
    try:
        with Session(engine) as db:
            membership = db.get(ProjectUser, project_user_id)
            if not membership:
                return False, "Membership not found."
            details = {"project_id": membership.project_id, "user_id": membership.user_id}
            db.delete(membership)
            _audit(db, actor_id, "REMOVE_PROJECT_MEMBER", "PROJECT_USER", project_user_id, details)
            db.commit()
            return True, "Project access removed."
    finally:
        engine.dispose()


def project_members(database_url: str, project_id: int):
    engine = create_database_engine(database_url)
    try:
        with Session(engine) as db:
            return list(db.scalars(select(ProjectUser).options(joinedload(ProjectUser.user), joinedload(ProjectUser.role)).where(ProjectUser.project_id == project_id).order_by(ProjectUser.id)).all())
    finally:
        engine.dispose()
