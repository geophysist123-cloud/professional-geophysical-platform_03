from auth.service import initialize_security_data
from sqlalchemy import create_engine

from database.models import Base


def create_application_schema(database_url: str) -> None:
    engine = create_engine(database_url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    engine.dispose()

    initialize_security_data(database_url)
