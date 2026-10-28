from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import select, func
from ..extensions import db
from ..models import Sale, Product, Store, StockMovement, Location, User
from .reorder import utc_bounds, recommendations
from .inventory import quantity
from .common import DomainError


def report(store_id, start=None, end=None):
    store = db.session.get(Store, store_id)
    today = datetime.now(ZoneInfo(store.timezone)).date()
    try:
        start = datetime.strptime(start, "%Y-%m-%d").date() if start else today-timedelta(days=29)
        end = datetime.strptime(end, "%Y-%m-%d").date() if end else today
    except ValueError as exc:
        raise DomainError("Enter valid report dates.") from exc
    if end < start or (end-start).days > 366:
        raise DomainError("Select an ordered date range of at most 367 days.")
    lo, hi = utc_bounds(start, end+timedelta(days=1), store.timezone)
    sales = db.session.scalars(select(Sale).where(Sale.store_id == store_id,
        Sale.effective_at >= lo, Sale.effective_at < hi).order_by(Sale.effective_at)).all()
    products = db.session.scalars(select(Product).where(Product.store_id == store_id)).all()
    by_id = {p.id:p for p in products}
    units = {p.id:0 for p in products if not p.archived}
    daily = { (start+timedelta(days=i)).isoformat():0 for i in range((end-start).days+1)}
    for sale in sales:
        units[sale.product_id] = units.get(sale.product_id, 0)+sale.quantity
        day = sale.effective_at.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo(store.timezone)).date().isoformat()
        daily[day] += sale.quantity
    ranked = sorted(((by_id[k], v) for k,v in units.items()), key=lambda t:(-t[1], t[0].name))
    active_ranked = [(p,q) for p,q in ranked if not p.archived]
    recs = recommendations(store_id)
    activity = db.session.execute(select(StockMovement, Product.name, Location.code, User.name).join(
        Product, Product.id == StockMovement.product_id).join(Location, Location.id == StockMovement.location_id).join(
        User, User.id == StockMovement.actor_id).where(StockMovement.store_id == store_id).order_by(
        StockMovement.id.desc()).limit(12)).all()
    return dict(start=start, end=end, timezone=store.timezone, sales=sales, products=by_id,
        revenue=sum(s.quantity*s.price_cents for s in sales), units=sum(s.quantity for s in sales),
        stock_value=sum(quantity(store_id,p.id)*p.cost_cents for p in products),
        low_count=sum(r["low"] for r in recs), risk_count=sum(r["risk"] for r in recs),
        fastest=ranked[:5], slowest=sorted(active_ranked,key=lambda t:(t[1],t[0].name))[:5],
        chart={"labels":list(daily), "values":list(daily.values())}, activity=activity)
