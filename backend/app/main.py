from contextlib import asynccontextmanager

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
from app.intensive_login_routes import router as intensive_login_router
from app.knowledge_routes import router as knowledge_router
from app.knowledge_library_routes import router as knowledge_library_router
from app.knowledge_mcp import knowledge_mcp_app, mcp as knowledge_mcp
from app.course_structure_routes import router as course_structure_router
from app.course_material_routes import router as course_material_router
from app.product_catalog_routes import router as product_catalog_router
from app.recipe_routes import router as recipe_router
from app.calorie_course_routes import router as calorie_course_router
from app.blog_routes import router as blog_router
from app.public_video_analytics_routes import router as public_video_analytics_router
from app.public_site_routes import router as public_site_router
from app.database import get_db

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with knowledge_mcp.session_manager.run():
        yield


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
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
app.include_router(intensive_login_router)
app.include_router(intensive_router)
app.include_router(knowledge_router)
app.include_router(knowledge_library_router)
app.include_router(course_structure_router)
app.include_router(course_material_router)
app.include_router(product_catalog_router)
app.include_router(recipe_router)
app.include_router(calorie_course_router)
app.include_router(blog_router)
app.include_router(public_video_analytics_router)
app.include_router(public_site_router)
app.mount("/mcp", knowledge_mcp_app)


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
