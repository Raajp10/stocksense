"""Store-scoped domain records. Quantities are units, money is integer cents."""
from datetime import datetime, timezone
from uuid import uuid4
from flask_login import UserMixin
from sqlalchemy import CheckConstraint, UniqueConstraint, ForeignKeyConstraint
from .extensions import db


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def token():
    return uuid4().hex


class Store(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    timezone = db.Column(db.String(60), nullable=False, default="America/Chicago")
    revision = db.Column(db.Integer, nullable=False, default=0)


class Scoped:
    id = db.Column(db.Integer, primary_key=True)
    store_id = db.Column(db.Integer, db.ForeignKey("store.id"), nullable=False, index=True)


class User(UserMixin, Scoped, db.Model):
    email = db.Column(db.String(150), nullable=False, unique=True)
    name = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(10), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    __table_args__ = (UniqueConstraint("store_id", "id"), CheckConstraint("role IN ('owner','staff')"))

    @property
    def is_active(self):
        return self.active


class Supplier(Scoped, db.Model):
    name = db.Column(db.String(100), nullable=False)
    contact = db.Column(db.String(250), nullable=False, default="")
    email = db.Column(db.String(150), nullable=False, default="", server_default="")
    phone = db.Column(db.String(60), nullable=False, default="", server_default="")
    address = db.Column(db.String(500), nullable=False, default="", server_default="")
    lead_time_days = db.Column(db.Integer, nullable=False, default=3)
    safety_days = db.Column(db.Integer, nullable=False, default=2)
    archived = db.Column(db.Boolean, nullable=False, default=False)
    __table_args__ = (UniqueConstraint("store_id", "id"), CheckConstraint("lead_time_days >= 0 AND safety_days >= 0"))


class Product(Scoped, db.Model):
    supplier_id = db.Column(db.Integer, nullable=False)
    sku = db.Column(db.String(60), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(1000), nullable=False, default="")
    image_key = db.Column(db.String(100))
    qr_token = db.Column(db.String(32), nullable=False, unique=True, default=token)
    category = db.Column(db.String(60), nullable=False, default="General")
    unit = db.Column(db.String(30), nullable=False, default="unit")
    cost_cents = db.Column(db.Integer, nullable=False, default=0)
    price_cents = db.Column(db.Integer, nullable=False, default=0)
    reorder_level = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=now)
    archived = db.Column(db.Boolean, nullable=False, default=False)
    supplier = db.relationship("Supplier", foreign_keys="[Product.store_id, Product.supplier_id]", viewonly=True)
    __table_args__ = (
        UniqueConstraint("store_id", "id"), UniqueConstraint("store_id", "sku"),
        ForeignKeyConstraint(["store_id", "supplier_id"], ["supplier.store_id", "supplier.id"]),
        CheckConstraint("cost_cents >= 0 AND price_cents >= 0 AND reorder_level >= 0"),
    )

    @property
    def qr_payload(self):
        return f"stocksense:v1:product:{self.qr_token}"


class Location(Scoped, db.Model):
    code = db.Column(db.String(40), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    area = db.Column(db.String(60), nullable=False, default="")
    aisle = db.Column(db.String(40), nullable=False, default="")
    shelf = db.Column(db.String(40), nullable=False, default="")
    bin = db.Column(db.String(40), nullable=False, default="")
    kind = db.Column(db.String(20), nullable=False, default="general")
    archived = db.Column(db.Boolean, nullable=False, default=False)
    __table_args__ = (UniqueConstraint("store_id", "id"), UniqueConstraint("store_id", "code"),
                      CheckConstraint("kind IN ('shelf','backroom','general')"))


class StockBalance(Scoped, db.Model):
    product_id = db.Column(db.Integer, nullable=False)
    location_id = db.Column(db.Integer, nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    version = db.Column(db.Integer, nullable=False, default=0)
    __table_args__ = (
        UniqueConstraint("store_id", "product_id", "location_id"), CheckConstraint("quantity >= 0"),
        ForeignKeyConstraint(["store_id", "product_id"], ["product.store_id", "product.id"]),
        ForeignKeyConstraint(["store_id", "location_id"], ["location.store_id", "location.id"]),
    )


class Operation(Scoped, db.Model):
    """Durable idempotency receipt shared by manual and QR actions."""
    token = db.Column(db.String(64), nullable=False)
    fingerprint = db.Column(db.String(64), nullable=False)
    kind = db.Column(db.String(20), nullable=False)
    actor_id = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=now)
    result = db.Column(db.JSON, nullable=False, default=dict)
    __table_args__ = (UniqueConstraint("store_id", "token"), UniqueConstraint("store_id", "id"),
                      ForeignKeyConstraint(["store_id", "actor_id"], ["user.store_id", "user.id"]))


class Sale(Scoped, db.Model):
    product_id = db.Column(db.Integer, nullable=False)
    location_id = db.Column(db.Integer, nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price_cents = db.Column(db.Integer, nullable=False)
    actor_id = db.Column(db.Integer, nullable=False)
    operation_id = db.Column(db.Integer, nullable=False, unique=True)
    effective_at = db.Column(db.DateTime, nullable=False, default=now, index=True)
    __table_args__ = (
        CheckConstraint("quantity > 0 AND price_cents >= 0"),
        ForeignKeyConstraint(["store_id", "product_id"], ["product.store_id", "product.id"]),
        ForeignKeyConstraint(["store_id", "location_id"], ["location.store_id", "location.id"]),
        ForeignKeyConstraint(["store_id", "actor_id"], ["user.store_id", "user.id"]),
        ForeignKeyConstraint(["store_id", "operation_id"], ["operation.store_id", "operation.id"]),
    )


class StockTransfer(Scoped, db.Model):
    product_id = db.Column(db.Integer, nullable=False)
    source_id = db.Column(db.Integer, nullable=False)
    destination_id = db.Column(db.Integer, nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    operation_id = db.Column(db.Integer, nullable=False, unique=True)
    __table_args__ = (
        CheckConstraint("quantity > 0 AND source_id != destination_id"),
        ForeignKeyConstraint(["store_id", "product_id"], ["product.store_id", "product.id"]),
        ForeignKeyConstraint(["store_id", "source_id"], ["location.store_id", "location.id"]),
        ForeignKeyConstraint(["store_id", "destination_id"], ["location.store_id", "location.id"]),
        ForeignKeyConstraint(["store_id", "operation_id"], ["operation.store_id", "operation.id"]),
    )


class StockMovement(Scoped, db.Model):
    product_id = db.Column(db.Integer, nullable=False)
    location_id = db.Column(db.Integer, nullable=False)
    delta = db.Column(db.Integer, nullable=False)
    kind = db.Column(db.String(20), nullable=False)
    actor_id = db.Column(db.Integer, nullable=False)
    operation_id = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(250), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=now)
    __table_args__ = (
        UniqueConstraint("operation_id", "product_id", "location_id"),
        ForeignKeyConstraint(["store_id", "product_id"], ["product.store_id", "product.id"]),
        ForeignKeyConstraint(["store_id", "location_id"], ["location.store_id", "location.id"]),
        ForeignKeyConstraint(["store_id", "actor_id"], ["user.store_id", "user.id"]),
        ForeignKeyConstraint(["store_id", "operation_id"], ["operation.store_id", "operation.id"]),
    )


class ShelfRule(Scoped, db.Model):
    product_id = db.Column(db.Integer, nullable=False)
    shelf_id = db.Column(db.Integer, nullable=False)
    source_id = db.Column(db.Integer, nullable=False)
    target = db.Column(db.Integer, nullable=False)
    __table_args__ = (
        UniqueConstraint("store_id", "product_id", "shelf_id"), CheckConstraint("target >= 0 AND shelf_id != source_id"),
        ForeignKeyConstraint(["store_id", "product_id"], ["product.store_id", "product.id"]),
        ForeignKeyConstraint(["store_id", "shelf_id"], ["location.store_id", "location.id"]),
        ForeignKeyConstraint(["store_id", "source_id"], ["location.store_id", "location.id"]),
    )


class PurchaseOrder(Scoped, db.Model):
    supplier_id = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="draft")
    created_by = db.Column(db.Integer, nullable=False)
    approved_by = db.Column(db.Integer)
    received_by = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, nullable=False, default=now)
    approved_at = db.Column(db.DateTime)
    approval_note = db.Column(db.String(250), nullable=False, default="", server_default="")
    received_at = db.Column(db.DateTime)
    items = db.relationship("PurchaseOrderItem", backref="order", lazy="selectin")
    __table_args__ = (
        UniqueConstraint("store_id", "id"), CheckConstraint("status IN ('draft','approved','received','cancelled')"),
        ForeignKeyConstraint(["store_id", "supplier_id"], ["supplier.store_id", "supplier.id"]),
        ForeignKeyConstraint(["store_id", "created_by"], ["user.store_id", "user.id"]),
        ForeignKeyConstraint(["store_id", "approved_by"], ["user.store_id", "user.id"]),
        ForeignKeyConstraint(["store_id", "received_by"], ["user.store_id", "user.id"]),
    )


class PurchaseOrderItem(Scoped, db.Model):
    order_id = db.Column(db.Integer, nullable=False)
    product_id = db.Column(db.Integer, nullable=False)
    destination_id = db.Column(db.Integer, nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    cost_cents = db.Column(db.Integer, nullable=False)
    __table_args__ = (
        UniqueConstraint("order_id", "product_id"), CheckConstraint("quantity > 0 AND cost_cents >= 0"),
        ForeignKeyConstraint(["store_id", "order_id"], ["purchase_order.store_id", "purchase_order.id"]),
        ForeignKeyConstraint(["store_id", "product_id"], ["product.store_id", "product.id"]),
        ForeignKeyConstraint(["store_id", "destination_id"], ["location.store_id", "location.id"]),
    )


class StockCountRequest(Scoped, db.Model):
    product_id = db.Column(db.Integer, nullable=False)
    location_id = db.Column(db.Integer, nullable=False)
    counted_quantity = db.Column(db.Integer, nullable=False)
    observed_version = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(250), nullable=False)
    requester_id = db.Column(db.Integer, nullable=False)
    approver_id = db.Column(db.Integer)
    status = db.Column(db.String(20), nullable=False, default="pending")
    created_at = db.Column(db.DateTime, nullable=False, default=now)
    __table_args__ = (
        CheckConstraint("counted_quantity >= 0"), CheckConstraint("status IN ('pending','approved','rejected')"),
        ForeignKeyConstraint(["store_id", "product_id"], ["product.store_id", "product.id"]),
        ForeignKeyConstraint(["store_id", "location_id"], ["location.store_id", "location.id"]),
        ForeignKeyConstraint(["store_id", "requester_id"], ["user.store_id", "user.id"]),
        ForeignKeyConstraint(["store_id", "approver_id"], ["user.store_id", "user.id"]),
    )


class DocumentImport(Scoped, db.Model):
    source_name = db.Column(db.String(200), nullable=False)
    source_hash = db.Column(db.String(64), nullable=False)
    source_text = db.Column(db.Text, nullable=False)
    source_key = db.Column(db.String(100))
    data = db.Column(db.JSON, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="draft")
    version = db.Column(db.Integer, nullable=False, default=0)
    created_by = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=now)
    finalized_at = db.Column(db.DateTime)
    supplier_id = db.Column(db.Integer)
    order_id = db.Column(db.Integer)
    dedupe_key = db.Column(db.String(200))
    __table_args__ = (
        UniqueConstraint("store_id", "source_hash"), UniqueConstraint("store_id", "dedupe_key"),
        CheckConstraint("status IN ('draft','reviewed','received','ordered')"),
        ForeignKeyConstraint(["store_id", "created_by"], ["user.store_id", "user.id"]),
        ForeignKeyConstraint(["store_id", "supplier_id"], ["supplier.store_id", "supplier.id"]),
        ForeignKeyConstraint(["store_id", "order_id"], ["purchase_order.store_id", "purchase_order.id"]),
    )


class CountSession(Scoped, db.Model):
    title = db.Column(db.String(120), nullable=False)
    reason = db.Column(db.String(250), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="counting")
    blind = db.Column(db.Boolean, nullable=False, default=True)
    created_by = db.Column(db.Integer, nullable=False)
    assignee_id = db.Column(db.Integer)
    reviewed_by = db.Column(db.Integer)
    due_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, nullable=False, default=now)
    submitted_at = db.Column(db.DateTime)
    reviewed_at = db.Column(db.DateTime)
    events = db.Column(db.JSON, nullable=False, default=list)
    lines = db.relationship("CountSessionLine", lazy="selectin", backref="session")
    __table_args__ = (
        UniqueConstraint("store_id", "id"),
        CheckConstraint("status IN ('counting','submitted','approved','rejected')"),
        ForeignKeyConstraint(["store_id", "created_by"], ["user.store_id", "user.id"]),
        ForeignKeyConstraint(["store_id", "assignee_id"], ["user.store_id", "user.id"]),
        ForeignKeyConstraint(["store_id", "reviewed_by"], ["user.store_id", "user.id"]),
    )


    @property
    def display_status(self):
        if self.status=='rejected' and self.events and self.events[-1].get('action')=='Cancelled before submission':
            return 'Cancelled'
        return self.status.title()


class CountSessionLine(Scoped, db.Model):
    session_id = db.Column(db.Integer, nullable=False)
    product_id = db.Column(db.Integer, nullable=False)
    location_id = db.Column(db.Integer, nullable=False)
    expected_quantity = db.Column(db.Integer, nullable=False)
    observed_version = db.Column(db.Integer, nullable=False)
    counted_quantity = db.Column(db.Integer)
    note = db.Column(db.String(250), nullable=False, default="")
    __table_args__ = (
        UniqueConstraint("session_id", "product_id", "location_id"),
        CheckConstraint("expected_quantity >= 0 AND (counted_quantity IS NULL OR counted_quantity >= 0)"),
        ForeignKeyConstraint(["store_id", "session_id"], ["count_session.store_id", "count_session.id"]),
        ForeignKeyConstraint(["store_id", "product_id"], ["product.store_id", "product.id"]),
        ForeignKeyConstraint(["store_id", "location_id"], ["location.store_id", "location.id"]),
    )
