from fastapi import FastAPI
from sqlalchemy import inspect, text

from app.database import Base, engine
from app.routes.auth import router as auth_router
from app.routes.books import router as books_router
from app.routes.admin import router as admin_router
from app.routes.notifications import router as notifications_router
from app.routes.stats import router as stats_router

app = FastAPI(title="Library Management System API", version="1.0.0")


def _run_startup_migrations() -> None:
    """Apply lightweight schema changes for existing SQLite databases."""
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "books" not in table_names:
        return

    book_columns = {column["name"] for column in inspector.get_columns("books")}
    if "publication_year" not in book_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE books ADD COLUMN publication_year INTEGER"))


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    _run_startup_migrations()


@app.get("/")
def root():
    return {"message": "LMS API is running"}


app.include_router(auth_router)
app.include_router(books_router)
app.include_router(admin_router)
app.include_router(notifications_router)
app.include_router(stats_router)
