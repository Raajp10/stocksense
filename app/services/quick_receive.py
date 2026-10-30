"""Build a safe receipt review from item corrections and saved OCR suggestions."""
from uuid import uuid4
from werkzeug.datastructures import MultiDict
from sqlalchemy import select
from ..extensions import db
from ..models import Location,Supplier,Product
from .common import DomainError,scoped,whole


def default_location(store_id):
    locations=db.session.scalars(select(Location).where(Location.store_id==store_id,Location.archived.is_(False)).order_by(Location.id)).all()
    return next((l.id for l in locations if l.kind=='backroom'),locations[0].id if locations else '')


def review_form(actor,draft,submitted):
    """Extra supplier/catalog fields are server defaults, never worker privileges."""
    metadata=dict(draft.data['metadata'])
    name=metadata.get('supplier_name','').strip()
    if not name or name.rstrip(':').casefold() in ('invoice','receipt','date','total','delivery','bill to','shipping'):
        name='Unspecified supplier'
    metadata['supplier_name']=name
    matched=draft.data.get('supplier_id')
    supplier=scoped(Supplier,whole(matched,1),actor.store_id,True) if matched else db.session.scalar(select(Supplier).where(Supplier.store_id==actor.store_id,Supplier.archived.is_(False),Supplier.name.ilike(name)))
    form=MultiDict({**metadata,'version':submitted.get('version',''),'supplier_id':str(supplier.id) if supplier else ''})
    keys=submitted.getlist('line_key')
    if not 1<=len(keys)<=100 or len(set(keys))!=len(keys): raise DomainError('Keep between 1 and 100 item rows.')
    destination=submitted.get('destination','')
    for key in keys:
        if not key.isascii() or not key.isdigit() or len(key)>5: raise DomainError('Invalid item row.')
        original=draft.data['lines'][int(key)] if int(key)<len(draft.data['lines']) else {}
        prefix=f'line_{key}_'
        pid=submitted.get(prefix+'product_id',original.get('product_id','')).strip()
        product=scoped(Product,whole(pid,1),actor.store_id,True) if pid.isascii() and pid.isdigit() else None
        if pid and product is None: raise DomainError('Choose an available product.')
        values={
            'product_id':pid,'name':submitted.get(prefix+'name',original.get('name','')),
            'quantity':submitted.get(prefix+'quantity',''),'cost':submitted.get(prefix+'cost',''),
            'sku':product.sku if product else original.get('sku') or 'IMP-'+uuid4().hex[:8].upper(),
            'category':submitted.get(prefix+'category',original.get('category') or 'General') or 'General',
            'unit':submitted.get(prefix+'unit',original.get('unit') or 'unit') or 'unit',
            'price':f'{product.price_cents/100:.2f}' if product else f"{original.get('price_cents',0)/100:.2f}" if draft.status=='reviewed' else '0.00',
            'location_id':destination,'reorder_level':str(product.reorder_level) if product else '0',
            'source_total':original.get('source_total',''),'description':original.get('description',''),
        }
        form.add('line_key',key)
        for field,value in values.items(): form[prefix+field]=str(value)
    return form
