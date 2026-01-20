from sqlalchemy import text
from utils.database import get_session_factory
from sqlalchemy.exc import ProgrammingError, OperationalError


def drop_all_tables_and_recreate_schema(schema='public'):
    SessionFactory = get_session_factory()
    with SessionFactory() as session:
        conn = session.get_bind().connect()
        trans = conn.begin()
        try:
            # Terminate active connections to the target schema
            conn.execute(text(f"""
                SELECT pg_terminate_backend(pg_stat_activity.pid)
                FROM pg_stat_activity
                WHERE datname = current_database() AND pid <> pg_backend_pid();
            """))
            
            # Drop all tables in the schema
            conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE;"))
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema};"))
            
            trans.commit()
            print(f"All tables, schemas, and indexes in '{schema}' have been deleted and '{schema}' have been recreated.")
        except (ProgrammingError, OperationalError) as e:
            trans.rollback()
            print(f"Failed to drop schema '{schema}': {e}")
        finally:
            session.close()

# Run the function
drop_all_tables_and_recreate_schema()
