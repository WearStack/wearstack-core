from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import engine
from app.modules.auditlog import router as audit_router
from app.modules.auth.router import router as auth_router
from app.modules.business.router import router as business_router
from app.modules.catalog import images, lookups, products
from app.modules.customers.router import router as customers_router
from app.modules.inventory.router import router as inventory_router
from app.modules.purchasing.router import router as purchasing_router
from app.modules.reports.router import router as reports_router
from app.modules.roles.router import router as roles_router
from app.modules.sales.router import router as sales_router
from app.modules.setup.router import router as setup_router
from app.modules.stores.router import router as stores_router
from app.modules.sync.router import router as sync_router
from app.modules.users.router import router as users_router


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    # The interactive docs and schema describe every endpoint; only expose them in development.
    docs = settings.environment == "development"
    app = FastAPI(
        title=settings.app_name,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(setup_router)
    app.include_router(auth_router)
    for r in (
        stores_router,
        business_router,
        users_router,
        roles_router,
        audit_router,
        lookups.router,
        products.router,
        images.router,
        inventory_router,
        customers_router,
        sales_router,
        purchasing_router,
        reports_router,
        sync_router,
    ):
        app.include_router(r)

    app.mount("/media", StaticFiles(directory=images.media_path()), name="media")

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
