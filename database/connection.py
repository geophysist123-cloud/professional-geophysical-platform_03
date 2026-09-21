from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


def create_database_engine(
    database_url: str,
) -> Engine:
    """
    Create a SQLAlchemy database engine.

    Examples:

    SQLite:
        sqlite:///geophysical.db

    PostgreSQL:
        postgresql+psycopg://user:password@host/database

    MySQL:
        mysql+pymysql://user:password@host/database

    SQL Server:
        mssql+pyodbc://...
    """

    return create_engine(
        database_url,
        pool_pre_ping=True,
    )
