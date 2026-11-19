from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import engine
from app.modules.auditlog import router as audit_router
from app.modules.auth.router import router as auth_router
from app.modules.roles.router import router as roles_router
from app.modules.setup.router import router as setup_router
from app.modules.stores.router import router as stores_router
from app.modules.users.router import router as users_router


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title=settings.app_name)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(setup_router)
    app.include_router(auth_router)
    for r in (stores_router, users_router, roles_router, audit_router):
        app.include_router(r)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/db")
    def health_db() -> dict[str, str]:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok"}

    return app


app = create_app()
