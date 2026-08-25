from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.crm_routes import router as crm_router
from app.content_routes import router as content_router
from app.app_routes import router as app_router
from app.tilda_routes import router as tilda_router
from app.masterclass_routes import router as masterclass_router
from app.app_auth import router as app_auth_router
from app.access_routes import router as access_router
from app.pricing_routes import router as pricing_router
from app.intensive_routes import router as intensive_router
from app.knowledge_routes import router as knowledge_router
from app.course_structure_routes import router as course_structure_router
from app.product_catalog_routes import router as product_catalog_router
from app.database import get_db

settings = get_settings()
app = FastAPI(title=settings.app_name, version=settings.app_version)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
app.include_router(crm_router)
app.include_router(content_router)
app.include_router(app_router)
app.include_router(tilda_router)
app.include_router(masterclass_router)
app.include_router(app_auth_router)
app.include_router(access_router)
app.include_router(pricing_router)
app.include_router(intensive_router)
app.include_router(knowledge_router)
app.include_router(course_structure_router)
app.include_router(product_catalog_router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Confirm that the API process is running."""
    return {"status": "ok"}


@app.get("/ready", tags=["system"])
def ready(db: Session = Depends(get_db)) -> dict[str, str]:
    """Confirm that the API can reach PostgreSQL."""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc
    return {"status": "ready"}
