import hashlib
import hmac
import json
import os

os.environ["DATABASE_URL"] = "sqlite:///./test_saas.db"

import pytest
from fastapi.testclient import TestClient

from app.database import engine
from app.main import app
from app.models import Base, User

Base.metadata.create_all(bind=engine)
client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def register_user(email: str = "user@example.com", password: str = "StrongPass123"):
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()


def login_user(email: str, password: str):
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_auth_register_and_login():
    register_user("new_user@example.com", "StrongPass123")
    response = login_user("new_user@example.com", "StrongPass123")
    assert "access_token" in response
    assert response["token_type"] == "bearer"


def test_standard_user_cannot_access_admin():
    register_user("standard@example.com", "StrongPass123")
    token_payload = login_user("standard@example.com", "StrongPass123")
    response = client.get(
        "/api/admin/analytics",
        headers={"Authorization": f"Bearer {token_payload['access_token']}"},
    )
    assert response.status_code == 403


def test_catalog_and_checkout_flow():
    register_user("customer@example.com", "StrongPass123")
    login = login_user("customer@example.com", "StrongPass123")

    products = client.get("/api/products").json()
    assert products["total"] >= 1
    first_product = products["items"][0]

    response = client.post(
        "/api/orders/checkout",
        json={"items": [{"product_id": first_product["id"], "quantity": 1}]},
        headers={"Authorization": f"Bearer {login['access_token']}"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "pending"
    assert payload["total_amount"] > 0


def test_webhook_signature_and_duplicate_event_are_handled():
    register_user("customer2@example.com", "StrongPass123")
    login = login_user("customer2@example.com", "StrongPass123")

    products = client.get("/api/products").json()
    first_product = products["items"][0]
    checkout = client.post(
        "/api/orders/checkout",
        json={"items": [{"product_id": first_product["id"], "quantity": 1}]},
        headers={"Authorization": f"Bearer {login['access_token']}"},
    )
    order_id = checkout.json()["order_id"]

    payload = {"event_id": "evt-duplicate-1", "event_type": "order.paid", "order_id": order_id, "amount": 89.0, "currency": "USD"}
    body = json.dumps(payload).encode("utf-8")
    signature = hmac.new(b"change-me-webhook-secret", body, hashlib.sha256).hexdigest()

    invalid = client.post(
        "/api/webhooks/mock",
        content=body,
        headers={"Content-Type": "application/json", "X-Signature": "bad-signature"},
    )
    assert invalid.status_code == 401

    valid = client.post(
        "/api/webhooks/mock",
        content=body,
        headers={"Content-Type": "application/json", "X-Signature": signature},
    )
    assert valid.status_code == 200, valid.text
    assert valid.json()["status"] == "processed"

    duplicate = client.post(
        "/api/webhooks/mock",
        content=body,
        headers={"Content-Type": "application/json", "X-Signature": signature},
    )
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["status"] == "duplicate"

    admin = client.post(
        "/api/auth/register",
        json={"email": "admin@example.com", "password": "StrongPass123"},
    )
    assert admin.status_code == 200
    user_data = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "StrongPass123"}).json()
    admin_resp = client.get(
        "/api/admin/analytics",
        headers={"Authorization": f"Bearer {user_data['access_token']}"},
    )
    assert admin_resp.status_code == 403

    # create admin via backend directly for analytics verification
    from app.main import SessionLocal, get_password_hash
    from app.models import User as DbUser, UserRole

    with SessionLocal() as db:
        existing = db.query(DbUser).filter(DbUser.email == "admin@saas.local").first()
        if existing is None:
            admin_user = DbUser(
                email="admin@saas.local",
                password_hash=get_password_hash("AdminPass123!"),
                role=UserRole.admin.value,
            )
            db.add(admin_user)
            db.commit()

    admin_login = client.post("/api/auth/login", json={"email": "admin@saas.local", "password": "AdminPass123!"}).json()
    analytics = client.get(
        "/api/admin/analytics",
        headers={"Authorization": f"Bearer {admin_login['access_token']}"},
    )
    assert analytics.status_code == 200, analytics.text
    assert analytics.json()["total_sales"] >= 0


def test_admin_analytics_available_to_admin():
    from app.main import SessionLocal, get_password_hash
    from app.models import User as DbUser, UserRole

    with SessionLocal() as db:
        existing = db.query(DbUser).filter(DbUser.email == "admin@saas.local").first()
        if existing is None:
            admin_user = DbUser(
                email="admin@saas.local",
                password_hash=get_password_hash("AdminPass123!"),
                role=UserRole.admin.value,
            )
            db.add(admin_user)
            db.commit()

    login = client.post("/api/auth/login", json={"email": "admin@saas.local", "password": "AdminPass123!"})
    assert login.status_code == 200, login.text
    response = client.get(
        "/api/admin/analytics",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert response.status_code == 200
    analytics = response.json()
    assert "total_sales" in analytics
    assert "user_signups" in analytics
