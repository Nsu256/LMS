from fastapi import FastAPI

from app.database import Base, engine
from app.routes.auth import router as auth_router
from app.routes.books import router as books_router
from app.routes.admin import router as admin_router

app = FastAPI(title="Library Management System API", version="1.0.0")


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/")
def root():
    return {"message": "LMS API is running"}


app.include_router(auth_router)
app.include_router(books_router)
app.include_router(admin_router)
