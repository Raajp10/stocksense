from flask import abort
from sqlalchemy import select, update
from ..extensions import db
from ..models import Store, User


class DomainError(ValueError):
    pass


def scoped(model, ident, store_id, active=False):
    obj = db.session.scalar(select(model).where(model.id == ident, model.store_id == store_id))
    if not obj or (active and getattr(obj, "archived", False)):
        raise DomainError("Record not found or unavailable.")
    return obj


def lock_store(actor, owner=False):
    # A write lock is portable: SQLite locks writers; PostgreSQL locks this store row.
    # All mutations use this ordering before reading balances/status/version.
    sid, uid = actor.store_id, actor.id
    db.session.execute(update(Store).where(Store.id == sid).values(revision=Store.revision+1))
    db.session.expire_all()
    user = scoped(User, uid, sid)
    if not user.active or user.role not in ("owner", "staff") or (owner and user.role != "owner"):
        raise DomainError("This action requires an active authorized account.")
    return user


def whole(value, minimum=0, maximum=1_000_000_000):
    text = str(value)
    if not text.isascii() or not text.isdigit() or not minimum <= int(text) <= maximum:
        raise DomainError(f"Enter a whole number between {minimum:,} and {maximum:,}.")
    return int(text)
