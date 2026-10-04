"""Isolated read-only UI preview; never connects to production or a stored DB."""
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.blog_routes import router
from app.database import Base, get_db

engine = create_engine('sqlite+pysqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
Base.metadata.create_all(engine)
app = FastAPI()
app.include_router(router)

def database():
    with Session(engine) as db:
        yield db

app.dependency_overrides[get_db] = database

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8784)
