import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.core.config import settings
from app.utils.workspace import initialize_workspace

# Ensure workspace is initialized before running the database engine
initialize_workspace()

# Resolve absolute path to database URL
db_url = settings.METADATA_DB_URL
if db_url.startswith("sqlite:///"):
    # Ensure folder containing database file exists
    db_relative_path = db_url.split("sqlite:///")[1]
    db_absolute_path = os.path.abspath(db_relative_path)
    os.makedirs(os.path.dirname(db_absolute_path), exist_ok=True)
    db_url = f"sqlite:///{db_absolute_path}"

engine = create_engine(
    db_url,
    connect_args={"check_same_thread": False}  # Needed for SQLite multithreading
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base() # base class for all models, has catalogue of all tables

def get_db():
    """
    Dependency generator yielding db session.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
