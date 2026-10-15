from __future__ import annotations

import hashlib
import hmac
import json
import math
from datetime import datetime, timedelta
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal, engine
from app.models import Base, Order, OrderItem, OrderStatus, Product, Transaction, TransactionStatus, User, UserRole, WebhookEvent
from app.schemas import (
    AnalyticsSummary,
    CheckoutRequest,
    CheckoutResponse,
    ProductListResponse,
    ProductRead,
    TokenResponse,
    UserCreate,
    UserRead,
    WebhookPayload,
    WebhookResponse,
)

APP_TITLE = settings.app_name
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

app = FastAPI(title=APP_TITLE, version="1.0.0", swagger_ui_parameters={"persistAuthorization": True})
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_access_token(subject: str, role: str) -> str:
    expires_at = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": subject, "role": role, "exp": expires_at}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def ensure_seed_data() -> None:
    db = SessionLocal()
    try:
        if not db.query(User).first():
            admin = User(
                email=settings.admin_email,
                password_hash=get_password_hash(settings.admin_password),
                role=UserRole.admin.value,
            )
            db.add(admin)

        if db.query(Product).count() == 0:
            products = [
                Product(
                    name="Productivity Suite",
                    sku="PROD-1001",
                    category="software",
                    description="All-in-one workflow management for growing teams.",
                    price=89.0,
                    stock=25,
                    is_active=True,
                ),
                Product(
                    name="Analytics Studio",
                    sku="PROD-1002",
                    category="analytics",
                    description="Insight dashboards, forecasting, and monthly KPIs.",
                    price=120.0,
                    stock=18,
                    is_active=True,
                ),
                Product(
                    name="Ops Monitor",
                    sku="PROD-1003",
                    category="monitoring",
                    description="Infrastructure monitoring with incident alerts.",
                    price=64.5,
                    stock=35,
                    is_active=True,
                ),
                Product(
                    name="Billing Flow",
                    sku="PROD-1004",
                    category="finance",
                    description="Subscription billing logic for recurring revenue platforms.",
                    price=154.0,
                    stock=12,
                    is_active=True,
                ),
                Product(
                    name="Customer Portal",
                    sku="PROD-1005",
                    category="support",
                    description="Self-serve portal for account updates and tickets.",
                    price=92.0,
                    stock=22,
                    is_active=True,
                ),
            ]
            db.add_all(products)
        db.commit()
    finally:
        db.close()


@app.on_event("startup")
def startup_event() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_seed_data()


@app.get("/health")
def health_check() -> dict[str, Any]:
    return {"status": "ok", "service": settings.app_name}


@app.get("/api/docs/health")
def docs_health() -> dict[str, str]:
    return {"status": "docs-ok"}


def authenticate_user(email: str, password: str, db: Session) -> User | None:
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password_hash):
        return None
    return user


def get_current_user(
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        email: str | None = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError as exc:
        raise credentials_exception from exc

    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise credentials_exception
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.admin.value:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


@app.post("/api/auth/register", response_model=UserRead)
def register_user(payload: UserCreate, db: Session = Depends(get_db)) -> User:
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="User with this email already exists")

    user = User(
        email=payload.email,
        password_hash=get_password_hash(payload.password),
        role=UserRole.standard.value,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/api/auth/login", response_model=TokenResponse)
def login_user(payload: dict, db: Session = Depends(get_db)) -> dict[str, Any]:
    email = (payload or {}).get("email")
    password = (payload or {}).get("password")
    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password are required")

    user = authenticate_user(email, password, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(user.email, user.role)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": user.id, "email": user.email, "role": user.role},
    }


@app.get("/api/users/me", response_model=UserRead)
def get_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@app.get("/api/products", response_model=ProductListResponse)
def list_products(
    search: str | None = None,
    category: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    page: int = 1,
    page_size: int = 10,
    db: Session = Depends(get_db),
) -> ProductListResponse:
    page = max(1, page)
    page_size = max(1, min(page_size, 50))

    if db.query(Product).count() == 0:
        ensure_seed_data()

    query = db.query(Product).filter(Product.is_active.is_(True))
    if search:
        like_pattern = f"%{search.lower()}%"
        query = query.filter(or_(Product.name.ilike(like_pattern), Product.description.ilike(like_pattern)))
    if category:
        query = query.filter(Product.category.ilike(category))
    if min_price is not None:
        query = query.filter(Product.price >= min_price)
    if max_price is not None:
        query = query.filter(Product.price <= max_price)

    total = query.count()
    items = query.order_by(Product.id.asc()).offset((page - 1) * page_size).limit(page_size).all()
    total_pages = math.ceil(total / page_size) if total else 0

    return ProductListResponse(
        items=[ProductRead.model_validate(product) for product in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@app.get("/api/products/{product_id}", response_model=ProductRead)
def get_product(product_id: int, db: Session = Depends(get_db)) -> Product:
    product = db.query(Product).filter(Product.id == product_id, Product.is_active.is_(True)).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@app.post("/api/orders/checkout", response_model=CheckoutResponse)
def create_checkout(
    payload: CheckoutRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if not payload.items:
        raise HTTPException(status_code=400, detail="At least one item is required")

    order = Order(user_id=current_user.id, status=OrderStatus.pending.value, total_amount=0.0)
    db.add(order)
    db.flush()

    total_amount = 0.0
    for item in payload.items:
        product = db.query(Product).filter(Product.id == item.product_id, Product.is_active.is_(True)).first()
        if product is None:
            raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")
        if item.quantity > product.stock:
            raise HTTPException(status_code=400, detail=f"Insufficient stock for {product.name}")

        line_total = product.price * item.quantity
        total_amount += float(line_total)
        product.stock -= item.quantity

        order_item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            quantity=item.quantity,
            unit_price=product.price,
            line_total=float(line_total),
        )
        db.add(order_item)

    order.total_amount = total_amount
    db.flush()

    transaction = Transaction(
        order_id=order.id,
        amount=total_amount,
        status=TransactionStatus.pending.value,
        provider="mock_gateway",
    )
    db.add(transaction)
    db.commit()
    db.refresh(order)
    db.refresh(transaction)

    return {
        "order_id": order.id,
        "transaction_id": transaction.id,
        "status": order.status,
        "total_amount": total_amount,
    }


@app.get("/api/admin/analytics", response_model=AnalyticsSummary)
def get_admin_analytics(
    _current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    total_sales = db.query(func.coalesce(func.sum(Transaction.amount), 0.0)).filter(Transaction.status == TransactionStatus.paid.value).scalar() or 0.0
    user_signups = db.query(User).count()

    order_logs = (
        db.query(Order.id, Order.status, Order.total_amount, User.email, Order.created_at)
        .join(User, User.id == Order.user_id)
        .order_by(Order.created_at.desc())
        .limit(10)
        .all()
    )
    order_logs_payload = [
        {
            "order_id": order_id,
            "status": status,
            "total_amount": total_amount,
            "customer_email": email,
            "created_at": created_at.isoformat() if created_at else None,
        }
        for order_id, status, total_amount, email, created_at in order_logs
    ]

    order_status_summary = [
        {"status": status, "count": count}
        for status, count in db.query(Order.status, func.count(Order.id)).group_by(Order.status).all()
    ]
    transaction_status_summary = [
        {"status": status, "count": count}
        for status, count in db.query(Transaction.status, func.count(Transaction.id)).group_by(Transaction.status).all()
    ]

    return {
        "total_sales": float(total_sales),
        "user_signups": user_signups,
        "order_logs": order_logs_payload,
        "order_status_summary": order_status_summary,
        "transaction_status_summary": transaction_status_summary,
    }


@app.post("/api/webhooks/mock", response_model=WebhookResponse)
async def handle_mock_webhook(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    signature = request.headers.get("X-Signature") or request.headers.get("X-Webhook-Signature")
    if not signature:
        raise HTTPException(status_code=401, detail="Missing webhook signature")

    raw_body = await request.body()
    expected_signature = hmac.new(settings.webhook_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = await request.json()
    except Exception as exc:  # pragma: no cover - malformed JSON handling
        raise HTTPException(status_code=400, detail="Malformed JSON payload") from exc

    validation = WebhookPayload.model_validate(payload)

    processed_event = db.query(WebhookEvent).filter(WebhookEvent.event_id == validation.event_id).first()
    if processed_event:
        return {"status": "duplicate", "message": "Event already processed", "event_id": validation.event_id}

    event_record = WebhookEvent(
        event_id=validation.event_id,
        event_type=validation.event_type,
        payload=json.dumps(payload),
        signature_valid=True,
        processed=False,
    )
    db.add(event_record)
    db.flush()

    order = db.query(Order).filter(Order.id == validation.order_id).first()
    if order is not None:
        transaction = db.query(Transaction).filter(Transaction.order_id == order.id).order_by(Transaction.id.desc()).first()
        if transaction is not None and transaction.status != TransactionStatus.paid.value:
            transaction.status = TransactionStatus.paid.value
            transaction.updated_at = datetime.utcnow()
            order.status = OrderStatus.paid.value
            order.updated_at = datetime.utcnow()

    event_record.processed = True
    event_record.processed_at = datetime.utcnow()
    db.commit()

    return {"status": "processed", "message": "Webhook processed", "event_id": validation.event_id}


@app.get("/api/admin/users")
def list_users(
    _current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    users = db.query(User).order_by(User.created_at.desc()).all()
    return [{"id": user.id, "email": user.email, "role": user.role} for user in users]
