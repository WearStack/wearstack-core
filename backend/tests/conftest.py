import os
import tempfile
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from alembic import command

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://wearstack:wearstack@localhost:5434/wearstack_test"
)
# Must be set before the app (and its cached settings/engine) is imported.
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["MEDIA_DIR"] = tempfile.mkdtemp(prefix="wearstack-test-media-")

from app.db.session import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

OWNER = {"email": "owner@example.com", "password": "owner-password-1"}


def _ensure_database() -> None:
    url = make_url(TEST_DB_URL)
    admin = url.set(database="postgres", drivername="postgresql")
    with psycopg.connect(admin.render_as_string(hide_password=False), autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname=%s", (url.database,))
        if not exists.fetchone():
            conn.execute(f'CREATE DATABASE "{url.database}"')


@pytest.fixture(scope="session", autouse=True)
def _migrated_db() -> Iterator[None]:
    _ensure_database()
    # Always start from an empty schema, so a stale test database can never mask a migration bug.
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP SCHEMA public CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA public")
    command.upgrade(Config("alembic.ini"), "head")  # exercises the real migrations
    yield


@pytest.fixture(autouse=True)
def _clean_db() -> Iterator[None]:
    yield
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.exec_driver_sql(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


SETUP_BODY: dict[str, Any] = {
    "business_name": "Test Clothing Co",
    "state_code": "27",
    "store_name": "Main Store",
    "store_code": "MAIN",
    "owner_name": "Olive Owner",
    "owner_email": OWNER["email"],
    "owner_password": OWNER["password"],
}


@pytest.fixture
def setup_ids(client: TestClient) -> dict[str, str]:
    res = client.post("/setup", json=SETUP_BODY)
    assert res.status_code == 201, res.text
    return res.json()


def login(client: TestClient, email: str, password: str) -> dict[str, str]:
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
def owner(client: TestClient, setup_ids: dict[str, str]) -> dict[str, str]:
    return login(client, OWNER["email"], OWNER["password"])


@pytest.fixture
def roles(client: TestClient, owner: dict[str, str]) -> dict[str, str]:
    """role name -> id"""
    return {r["name"]: r["id"] for r in client.get("/roles", headers=owner).json()}


@pytest.fixture
def make_user(client: TestClient, owner: dict[str, str], roles: dict[str, str]) -> Any:
    def _make(role: str, email: str, store_ids: list[str] | None = None) -> dict[str, str]:
        res = client.post(
            "/users",
            headers=owner,
            json={
                "email": email,
                "full_name": email.split("@")[0],
                "password": "user-password-1",
                "role_id": roles[role],
                "store_ids": store_ids or [],
            },
        )
        assert res.status_code == 201, res.text
        return login(TestClient(app), email, "user-password-1")

    return _make


@pytest.fixture
def store_id(client: TestClient, owner: dict[str, str]) -> str:
    return str(client.get("/stores", headers=owner).json()[0]["id"])


@pytest.fixture
def make_product(client: TestClient, owner: dict[str, str]) -> Any:
    def _make(name: str = "Classic Shirt", price: str = "1299.00", **extra: Any) -> dict[str, Any]:
        body = {
            "name": name,
            "selling_price": price,
            "variants": [{"size": "M", "colour": "Blue"}, {"size": "L", "colour": "Blue"}],
            **extra,
        }
        res = client.post("/products", headers=owner, json=body)
        assert res.status_code == 201, res.text
        return res.json()

    return _make
