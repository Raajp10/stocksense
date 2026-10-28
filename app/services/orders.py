from sqlalchemy import select
from ..extensions import db
from ..models import PurchaseOrder, PurchaseOrderItem, Product, Supplier, Location, now
from .common import DomainError, lock_store, scoped, whole
from .reorder import recommendations


def create_drafts(actor, destination_id, selected=None):
    try:
        actor = lock_store(actor, owner=True)
        scoped(Location, destination_id, actor.store_id, active=True)
        rows = recommendations(actor.store_id)
        groups = {}
        for row in rows:
            p, supplier = row["product"], row["supplier"]
            if row["suggested"] > 0 and not supplier.archived and (selected is None or p.id in selected):
                groups.setdefault(p.supplier_id, []).append(row)
        orders = []
        for supplier_id, items in groups.items():
            order = PurchaseOrder(store_id=actor.store_id, supplier_id=supplier_id, created_by=actor.id)
            db.session.add(order)
            db.session.flush()
            for row in items:
                p = row["product"]
                db.session.add(PurchaseOrderItem(store_id=actor.store_id, order_id=order.id,
                    product_id=p.id, destination_id=destination_id, quantity=row["suggested"], cost_cents=p.cost_cents))
            orders.append(order.id)
        db.session.commit()
        return orders
    except Exception:
        db.session.rollback()
        raise


def change_order(actor, order_id, action, edits=None):
    try:
        actor = lock_store(actor, owner=True)
        order = scoped(PurchaseOrder, order_id, actor.store_id)
        if action == "cancel":
            if order.status not in ("draft", "approved"):
                raise DomainError("Only draft or approved orders can be cancelled.")
            order.status = "cancelled"
        elif action in ("edit", "approve"):
            if order.status != "draft":
                raise DomainError("Only draft orders can be edited or approved.")
            if edits is not None:
                for item in list(order.items):
                    edit = edits.get(str(item.id), {})
                    qty = whole(edit.get("quantity", item.quantity))
                    dest = whole(edit.get("destination_id", item.destination_id), 1)
                    scoped(Location, dest, actor.store_id, active=True)
                    if qty == 0:
                        db.session.delete(item)
                        order.items.remove(item)
                    else:
                        item.quantity, item.destination_id = qty, dest
            if not order.items:
                raise DomainError("Keep at least one order line, or cancel this draft.")
            if action == "approve":
                scoped(Supplier, order.supplier_id, actor.store_id, active=True)
                current = {r["product"].id:r for r in recommendations(actor.store_id)}
                for item in order.items:
                    scoped(Product, item.product_id, actor.store_id, active=True)
                    scoped(Location, item.destination_id, actor.store_id, active=True)
                    if item.product_id not in current or item.quantity > current[item.product_id]["suggested"]:
                        raise DomainError("Demand or incoming stock changed. Reduce quantities to the current recommendation before approval.")
                order.status, order.approved_at, order.approved_by = "approved", now(), actor.id
        else:
            raise DomainError("Unknown order action.")
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
