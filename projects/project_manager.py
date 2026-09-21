from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.connection import create_database_engine
from database.models import AuditLog, Project, ProjectUser, Role, User


def _audit(db: Session, user_id: int | None, action: str, object_type: str, object_id: Any, details: dict):
    db.add(AuditLog(user_id=user_id, action=action, object_type=object_type,
                    object_id=str(object_id) if object_id is not None else None,
                    details=json.dumps(details, ensure_ascii=False)))


def get_project(database_url: str, project_id: int) -> Project | None:
    engine = create_database_engine(database_url)
    try:
        with Session(engine) as db:
            return db.get(Project, project_id)
    finally:
        engine.dispose()


def list_projects(database_url: str, user_id: int | None = None, is_superadmin: bool = False):
    """Return projects visible to a user. Superadmins see all projects."""
    engine = create_database_engine(database_url)
    try:
        with Session(engine) as db:
            stmt = select(Project).order_by(Project.name)
            if user_id is not None and not is_superadmin:
                stmt = stmt.join(ProjectUser, ProjectUser.project_id == Project.id).where(ProjectUser.user_id == user_id)
            return list(db.scalars(stmt).unique().all())
    finally:
        engine.dispose()


def create_project(database_url: str, actor_id: int, name: str, description: str = "",
                   country: str = "", region: str = "", crs_epsg: int | None = None,
                   crs_authority: str | None = None, crs_name: str | None = None,
                   crs_wkt: str | None = None, coordinate_units: str | None = None):
    name = name.strip()
    if not name:
        return False, "Project name is required."
    engine = create_database_engine(database_url)
    try:
        with Session(engine) as db:
            existing = db.execute(select(Project).where(Project.name == name)).scalar_one_or_none()
            if existing:
                return False, "A project with this name already exists."
            project = Project(name=name, description=description.strip() or None,
                              country=country.strip() or None, region=region.strip() or None,
                              crs_epsg=crs_epsg, crs_authority=crs_authority,
                              crs_name=crs_name, crs_wkt=crs_wkt, coordinate_units=coordinate_units)
            db.add(project)
            db.flush()
            _audit(db, actor_id, "CREATE_PROJECT", "PROJECT", project.id,
                   {"name": name, "country": country, "region": region, "crs_epsg": crs_epsg,
                    "crs_authority": crs_authority, "crs_name": crs_name, "coordinate_units": coordinate_units})
            db.commit()
            return True, f"Project '{name}' created."
    finally:
        engine.dispose()


def update_project(database_url: str, actor_id: int, project_id: int, name: str,
                   description: str = "", country: str = "", region: str = "",
                   crs_epsg: int | None = None, crs_authority: str | None = None,
                   crs_name: str | None = None, crs_wkt: str | None = None,
                   coordinate_units: str | None = None):
    name = name.strip()
    if not name:
        return False, "Project name is required."
    engine = create_database_engine(database_url)
    try:
        with Session(engine) as db:
            project = db.get(Project, project_id)
            if not project:
                return False, "Project not found."
            duplicate = db.execute(select(Project).where(Project.name == name, Project.id != project_id)).scalar_one_or_none()
            if duplicate:
                return False, "Another project already uses this name."
            before = {"name": project.name, "description": project.description, "country": project.country,
                      "region": project.region, "crs_epsg": project.crs_epsg,
                      "crs_authority": project.crs_authority, "crs_name": project.crs_name,
                      "coordinate_units": project.coordinate_units}
            project.name = name
            project.description = description.strip() or None
            project.country = country.strip() or None
            project.region = region.strip() or None
            project.crs_epsg = crs_epsg
            project.crs_authority = crs_authority
            project.crs_name = crs_name
            project.crs_wkt = crs_wkt
            project.coordinate_units = coordinate_units
            _audit(db, actor_id, "UPDATE_PROJECT", "PROJECT", project_id,
                   {"before": before, "after": {"name": name, "description": project.description,
                                                 "country": project.country, "region": project.region,
                                                 "crs_epsg": crs_epsg, "crs_authority": crs_authority,
                                                 "crs_name": crs_name, "coordinate_units": coordinate_units}})
            db.commit()
            return True, "Project updated."
    finally:
        engine.dispose()


def delete_project(database_url: str, actor_id: int, project_id: int):
    engine = create_database_engine(database_url)
    try:
        with Session(engine) as db:
            project = db.get(Project, project_id)
            if not project:
                return False, "Project not found."
            # Dataset/processing tables may reference this project without ORM cascades.
            # Refuse deletion when dependent datasets exist to protect project history.
            from database.models import Dataset
            if db.execute(select(Dataset.id).where(Dataset.project_id == project_id).limit(1)).first():
                return False, "Project cannot be deleted because it contains datasets."
            db.query(ProjectUser).filter(ProjectUser.project_id == project_id).delete(synchronize_session=False)
            name = project.name
            db.delete(project)
            _audit(db, actor_id, "DELETE_PROJECT", "PROJECT", project_id, {"name": name})
            db.commit()
            return True, "Project deleted."
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
            membership = db.execute(select(ProjectUser).where(ProjectUser.project_id == project_id,
                                                               ProjectUser.user_id == user_id)).scalar_one_or_none()
            if membership is None:
                membership = ProjectUser(project_id=project_id, user_id=user_id, role_id=role_id)
                db.add(membership)
                db.flush()
                action = "ADD_PROJECT_MEMBER"
            else:
                membership.role_id = role_id
                action = "UPDATE_PROJECT_MEMBER"
            _audit(db, actor_id, action, "PROJECT_USER", membership.id,
                   {"project_id": project_id, "user_id": user_id, "role_id": role_id})
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
    from sqlalchemy.orm import joinedload
    engine = create_database_engine(database_url)
    try:
        with Session(engine) as db:
            return list(db.scalars(select(ProjectUser).options(joinedload(ProjectUser.user), joinedload(ProjectUser.role))
                        .where(ProjectUser.project_id == project_id).order_by(ProjectUser.id)).all())
    finally:
        engine.dispose()
