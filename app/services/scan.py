import re
from sqlalchemy import select, or_
from ..extensions import db
from ..models import Product
from .common import DomainError


def resolve(store_id, value):
    value = value.strip()
    if value.startswith("stocksense:"):
        if not re.fullmatch(r"stocksense:v1:product:[a-f0-9]{32}", value):
            raise DomainError("Product not found.")
        condition = Product.qr_token == value.rsplit(":", 1)[1]
    elif re.fullmatch(r"[A-Za-z0-9_.-]{1,60}", value):
        condition = Product.sku == value
    else:
        raise DomainError("Product not found.")
    product = db.session.scalar(select(Product).where(Product.store_id == store_id,
                            Product.archived.is_(False), condition))
    if not product:
        raise DomainError("Product not found.")
    return product
