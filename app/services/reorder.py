from datetime import datetime, time, timedelta, timezone
from fractions import Fraction
from math import ceil
from zoneinfo import ZoneInfo
from sqlalchemy import select, func
from ..extensions import db
from ..models import Store, Product, Sale, PurchaseOrder, PurchaseOrderItem, ShelfRule, Location
from .inventory import quantity


def utc_bounds(start, end, zone):
    tz = ZoneInfo(zone)
    return (datetime.combine(start, time.min, tz).astimezone(timezone.utc).replace(tzinfo=None),
            datetime.combine(end, time.min, tz).astimezone(timezone.utc).replace(tzinfo=None))


def calculate(sold, days, coverage, threshold, stock, incoming=0):
    average = Fraction(sold, days) if days else Fraction(0)
    forecast = ceil(average * coverage)
    target = max(threshold, forecast)
    return dict(sold=sold, days=days, average=float(average), coverage=coverage,
        forecast=forecast, threshold=threshold, target=target, stock=stock, incoming=incoming,
        base=max(0, target-stock), suggested=max(0, target-stock-incoming),
        days_remaining=float(Fraction(stock)/average) if average else None,
        low=stock <= threshold, risk=bool(average and Fraction(stock)/average <= coverage),
        history="Insufficient history" if not days else "No recent sales" if not sold else "Recorded sales")


def recommendations(store_id, today=None):
    store = db.session.get(Store, store_id)
    today = today or datetime.now(ZoneInfo(store.timezone)).date()
    start = today-timedelta(days=14)
    start_utc, end_utc = utc_bounds(start, today, store.timezone)
    rows = []
    for p in db.session.scalars(select(Product).where(Product.store_id == store_id, Product.archived.is_(False)).order_by(Product.name)):
        created = p.created_at.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(store.timezone)).date()
        days = max(0, min(14, (today-created).days))
        effective_start = max(start, created)
        lo, _ = utc_bounds(effective_start, today, store.timezone)
        sold = db.session.scalar(select(func.coalesce(func.sum(Sale.quantity), 0)).where(
            Sale.store_id == store_id, Sale.product_id == p.id, Sale.effective_at >= lo, Sale.effective_at < end_utc))
        incoming = db.session.scalar(select(func.coalesce(func.sum(PurchaseOrderItem.quantity), 0)).join(
            PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.order_id).where(
            PurchaseOrder.store_id == store_id, PurchaseOrder.status == "approved", PurchaseOrderItem.product_id == p.id))
        supplier = p.supplier
        r = calculate(sold, days, supplier.lead_time_days+supplier.safety_days,
                      p.reorder_level, quantity(store_id, p.id), incoming)
        rows.append(dict(r, product=p, supplier=supplier, start=effective_start, end=today-timedelta(days=1)))
    return rows


def shelf_refills(store_id):
    rows = []
    for rule in db.session.scalars(select(ShelfRule).where(ShelfRule.store_id == store_id)):
        p = db.session.get(Product, rule.product_id)
        dest, source = db.session.get(Location, rule.shelf_id), db.session.get(Location, rule.source_id)
        if p.archived or dest.archived or source.archived:
            continue
        current, available = quantity(store_id, p.id, dest.id), quantity(store_id, p.id, source.id)
        gap = max(0, rule.target-current)
        rows.append(dict(rule=rule, product=p, destination=dest, source=source, current=current,
                         available=available, gap=gap, suggested=min(gap, available)))
    return rows
