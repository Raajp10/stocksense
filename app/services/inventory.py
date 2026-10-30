import hashlib
import json
import re
from sqlalchemy import select, update, func
from ..extensions import db
from ..models import (Product, Location, StockBalance, Operation, StockMovement,
    Sale, StockTransfer, StockCountRequest, PurchaseOrder, PurchaseOrderItem, now)
from .common import DomainError, scoped, lock_store, whole


def balance(store_id, product_id, location_id):
    row = db.session.scalar(select(StockBalance).where(
        StockBalance.store_id == store_id, StockBalance.product_id == product_id,
        StockBalance.location_id == location_id))
    return row


def quantity(store_id, product_id, location_id=None):
    query = select(func.coalesce(func.sum(StockBalance.quantity), 0)).where(
        StockBalance.store_id == store_id, StockBalance.product_id == product_id)
    if location_id is not None:
        query = query.where(StockBalance.location_id == location_id)
    return db.session.scalar(query)


def move(actor, op, product, location_id, delta, reason, kind=None):
    scoped(Location, location_id, actor.store_id, active=True)
    row = balance(actor.store_id, product.id, location_id)
    if row is None:
        row = StockBalance(store_id=actor.store_id, product_id=product.id,
                           location_id=location_id, quantity=0, version=0)
        db.session.add(row)
        db.session.flush()
    result = db.session.execute(update(StockBalance).where(StockBalance.id == row.id,
        StockBalance.quantity + delta >= 0).values(quantity=StockBalance.quantity+delta,
        version=StockBalance.version+1))
    if result.rowcount != 1:
        raise DomainError("Insufficient stock at the selected location.")
    db.session.add(StockMovement(store_id=actor.store_id, product_id=product.id,
        location_id=location_id, delta=delta, kind=kind or op.kind, actor_id=actor.id,
        operation_id=op.id, reason=reason[:250]))


def execute(actor, kind, payload, token):
    """One transaction for authorization, idempotency, balances, ledger and receipt."""
    try:
        actor = lock_store(actor, owner=kind in ("opening", "adjustment", "document_reversal", "count_session"))
        if not re.fullmatch(r"[a-zA-Z0-9_-]{16,64}", token or ""):
            raise DomainError("Invalid submission token. Reload the form.")
        fingerprint = hashlib.sha256(json.dumps({"kind": kind, "actor": actor.id,
            "payload": payload}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        previous = db.session.scalar(select(Operation).where(Operation.store_id == actor.store_id,
                                                               Operation.token == token))
        if previous:
            if previous.fingerprint != fingerprint:
                raise DomainError("Submission token was already used for a different action.")
            result = dict(previous.result, duplicate=True)
            db.session.commit()
            return result
        op = Operation(store_id=actor.store_id, token=token, fingerprint=fingerprint,
                       kind=kind, actor_id=actor.id)
        db.session.add(op)
        db.session.flush()
        result = {"operation_id": op.id}
        if kind in ("sale", "receipt", "transfer", "opening"):
            product = scoped(Product, whole(payload["product_id"], 1), actor.store_id, active=True)
            if kind == "sale" and product.price_cents <= 0:
                raise DomainError("Ask the owner to set a selling price for this new item before recording sales.")
            qty = whole(payload["quantity"], 1)
            source = whole(payload["location_id"], 1)
            reason = str(payload.get("reason", "")).strip()
            if kind == "receipt" and not reason:
                raise DomainError("Enter the supplier/delivery reference.")
            if kind == "opening" and db.session.scalar(select(StockMovement.id).where(
                    StockMovement.store_id == actor.store_id, StockMovement.product_id == product.id)):
                raise DomainError("Opening stock can only be recorded once before other movements.")
            if kind == "transfer":
                dest = whole(payload["destination_id"], 1)
                if source == dest:
                    raise DomainError("Choose different source and destination locations.")
                scoped(Location, dest, actor.store_id, active=True)
                move(actor, op, product, source, -qty, reason or "Internal transfer")
                move(actor, op, product, dest, qty, reason or "Internal transfer")
                db.session.add(StockTransfer(store_id=actor.store_id, product_id=product.id,
                    source_id=source, destination_id=dest, quantity=qty, operation_id=op.id))
            else:
                move(actor, op, product, source, -qty if kind == "sale" else qty,
                     reason or ("Recorded sale" if kind == "sale" else "Opening balance"))
                if kind == "sale":
                    db.session.add(Sale(store_id=actor.store_id, product_id=product.id,
                        location_id=source, quantity=qty, price_cents=product.price_cents,
                        actor_id=actor.id, operation_id=op.id))
            db.session.flush()
            result.update(product_id=product.id, total=quantity(actor.store_id, product.id))
        elif kind == "order_receipt":
            order = scoped(PurchaseOrder, whole(payload["order_id"], 1), actor.store_id)
            if order.status != "approved":
                raise DomainError("Only an approved, unreceived order can be received.")
            if not order.items:
                raise DomainError("Order has no items.")
            for item in sorted(order.items, key=lambda i: (i.product_id, i.destination_id)):
                product = scoped(Product, item.product_id, actor.store_id, active=True)
                move(actor, op, product, item.destination_id, item.quantity, f"Order #{order.id}", "order_receipt")
            order.status, order.received_at, order.received_by = "received", now(), actor.id
            result["order_id"] = order.id
        elif kind == "document_receipt":
            from .documents import receive_document
            result.update(receive_document(actor,op,payload))
        elif kind == "document_reversal":
            from .documents import reverse_receipt
            result.update(reverse_receipt(actor,op,payload))
        elif kind == "count_session":
            from .stocktakes import approve_session
            result.update(approve_session(actor,op,payload))
        elif kind == "adjustment":
            count = scoped(StockCountRequest, whole(payload["count_id"], 1), actor.store_id)
            if count.status != "pending":
                raise DomainError("Count is no longer pending.")
            product = scoped(Product, count.product_id, actor.store_id, active=True)
            row = balance(actor.store_id, product.id, count.location_id)
            version, current = (row.version, row.quantity) if row else (0, 0)
            if version != count.observed_version:
                raise DomainError("Stock changed since this count. Reject it and request a fresh count.")
            move(actor, op, product, count.location_id, count.counted_quantity-current, count.reason)
            count.status, count.approver_id = "approved", actor.id
            result["count_id"] = count.id
        else:
            raise DomainError("Unknown inventory action.")
        op.result = result
        db.session.commit()
        return dict(result, duplicate=False)
    except Exception:
        db.session.rollback()
        raise


def submit_count(actor, product_id, location_id, counted, reason):
    try:
        actor = lock_store(actor)
        product = scoped(Product, product_id, actor.store_id, active=True)
        scoped(Location, location_id, actor.store_id, active=True)
        if not reason.strip() or len(reason) > 250:
            raise DomainError("A count reason of 1–250 characters is required.")
        row = balance(actor.store_id, product.id, location_id)
        count = StockCountRequest(store_id=actor.store_id, product_id=product.id,
            location_id=location_id, counted_quantity=whole(counted),
            observed_version=row.version if row else 0, reason=reason,
            requester_id=actor.id)
        db.session.add(count)
        db.session.commit()
        return count
    except Exception:
        db.session.rollback()
        raise


def reconciliation(store_id):
    balances = db.session.scalars(select(StockBalance).where(StockBalance.store_id == store_id)).all()
    problems = []
    keys = {(b.product_id, b.location_id): b.quantity for b in balances}
    ledger = db.session.execute(select(StockMovement.product_id, StockMovement.location_id,
        func.sum(StockMovement.delta)).where(StockMovement.store_id == store_id).group_by(
        StockMovement.product_id, StockMovement.location_id)).all()
    totals = {(p, l): q for p, l, q in ledger}
    for key in keys.keys() | totals.keys():
        if keys.get(key, 0) != totals.get(key, 0):
            problems.append({"product_location": key, "balance": keys.get(key, 0), "ledger": totals.get(key, 0)})
    return problems
