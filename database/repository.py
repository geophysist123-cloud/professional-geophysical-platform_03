from sqlalchemy import create_engine, text


def test_database_connection(database_url: str) -> tuple[bool, str]:
    try:
        engine = create_engine(
            database_url,
            pool_pre_ping=True,
        )

        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        engine.dispose()

        return True, "Database connection successful."

    except Exception as exc:
        return False, f"Database connection failed: {exc}"
