from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field

# Configure the app for tests before anything imports settings.
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://saqient:saqient@localhost:5432/saqient_test"
)
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "true"
os.environ["DEMO_MODE"] = "false"
os.environ["STORAGE_LOCAL_PATH"] = tempfile.mkdtemp(prefix="saqient-test-storage-")
os.environ["CORS_ORIGINS"] = "http://localhost:5173"
os.environ["MAIL_BACKEND"] = "memory"
os.environ["APP_BASE_URL"] = "http://localhost:5173"

import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from alembic import command  # noqa: E402
from app import demo_content as dc  # noqa: E402
from app.db import get_engine, get_sessionmaker  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Base,
    Checklist,
    ChecklistKind,
    ChecklistState,
    ChecklistVersion,
    Membership,
    Organization,
    Requirement,
    Role,
    Severity,
    User,
)
from app.security import hash_password, login_limiter  # noqa: E402

PASSWORD = "correct-horse-battery"
_HASH = hash_password(PASSWORD)


@pytest.fixture(scope="session", autouse=True)
def _schema() -> Iterator[None]:
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    yield
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with get_engine().begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} CASCADE"))
    login_limiter.reset()


@pytest.fixture
def db() -> Iterator[Session]:
    with get_sessionmaker()() as session:
        yield session


@dataclass
class Tenant:
    org: Organization
    users: dict[Role, User] = field(default_factory=dict)
    checklist_version: ChecklistVersion | None = None


def make_tenant(db: Session, slug: str, with_checklist: bool = True) -> Tenant:
    org = Organization(name=f"Org {slug}", slug=slug)
    db.add(org)
    db.flush()
    tenant = Tenant(org=org)
    for role in Role:
        u = User(
            email=f"{role.value}@{slug}.example",
            full_name=f"{role.value} {slug}",
            password_hash=_HASH,
        )
        db.add(u)
        db.flush()
        db.add(Membership(org_id=org.id, user_id=u.id, role=role))
        tenant.users[role] = u
    if with_checklist:
        c = Checklist(org_id=org.id, name="Test checklist", kind=ChecklistKind.INTERNAL_POLICY)
        db.add(c)
        db.flush()
        v = ChecklistVersion(
            org_id=org.id, checklist_id=c.id, version_number=1, state=ChecklistState.PUBLISHED
        )
        db.add(v)
        db.flush()
        for i, raw in enumerate(dc.DEMO_REQUIREMENTS):
            db.add(
                Requirement(
                    org_id=org.id,
                    checklist_version_id=v.id,
                    ordinal=i,
                    code=str(raw["code"]),
                    title=str(raw["title"]),
                    description=str(raw["description"]),
                    severity=Severity(str(raw["severity"])),
                    check_config=raw["check_config"],
                )
            )  # type: ignore[arg-type]
        tenant.checklist_version = v
    db.commit()
    return tenant


@pytest.fixture
def tenant_a(db: Session) -> Tenant:
    return make_tenant(db, "a")


@pytest.fixture
def tenant_b(db: Session) -> Tenant:
    return make_tenant(db, "b")


class ApiClient(TestClient):
    csrf: str = ""

    def request(self, method: str, url: str, **kwargs):  # type: ignore[no-untyped-def,override]
        headers = dict(kwargs.pop("headers", None) or {})
        if self.csrf and method.upper() not in ("GET", "HEAD", "OPTIONS"):
            headers.setdefault("X-CSRF-Token", self.csrf)
        return super().request(method, url, headers=headers, **kwargs)


def login(user: User, password: str = PASSWORD) -> ApiClient:
    client = ApiClient(app)
    resp = client.post("/api/auth/login", json={"email": user.email, "password": password})
    assert resp.status_code == 200, resp.text
    client.csrf = resp.json()["csrf_token"]
    return client


def upload(
    client: ApiClient,
    data: bytes | None = None,
    filename: str = "policy.txt",
    mime: str = "text/plain",
    **form: str,
):  # type: ignore[no-untyped-def]
    payload = {
        "title": form.pop("title", "Synthetic policy"),
        "document_type": form.pop("document_type", "policy"),
        **form,
    }
    return client.post(
        "/api/documents",
        data=payload,
        files={"file": (filename, data or dc.policy_txt_bytes(), mime)},
    )


def ready_version_id(client: ApiClient, **kwargs) -> str:  # type: ignore[no-untyped-def]
    resp = upload(client, **kwargs)
    assert resp.status_code == 201, resp.text
    doc = client.get(f"/api/documents/{resp.json()['id']}").json()
    assert doc["latest_version"]["status"] == "ready", doc
    return str(doc["latest_version"]["id"])
