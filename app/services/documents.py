from datetime import datetime
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
import hashlib
import re
from uuid import uuid4
from sqlalchemy import select
from ..extensions import db
from ..models import DocumentImport, Product, Supplier, Location, PurchaseOrder, PurchaseOrderItem, now
from .common import DomainError, lock_store, scoped, whole
from .document_reader import parse_text


def money_cents(value, field='Unit cost'):
    try:
        number=Decimal(str(value).strip())
        if not number.is_finite() or number<0 or number>10_000_000 or number!=number.quantize(Decimal('.01')):
            raise InvalidOperation
        return int(number*100)
    except (InvalidOperation,ValueError):
        raise DomainError(f'{field}: enter a nonnegative amount with at most two decimal places.')


def bounded(value, limit, label, required=True):
    value=str(value or '').strip()
    if len(value)>limit or (required and not value):
        raise DomainError(f'{label}: enter {"1" if required else "0"}–{limit} characters.')
    return value


def match_suggestions(store_id, data):
    products=db.session.scalars(select(Product).where(Product.store_id==store_id,Product.archived.is_(False))).all()
    suppliers=db.session.scalars(select(Supplier).where(Supplier.store_id==store_id,Supplier.archived.is_(False))).all()
    data['supplier_id']=''
    for supplier in suppliers:
        if supplier.name.casefold()==data['metadata']['supplier_name'].casefold() or (
            supplier.email and supplier.email.casefold()==data['metadata']['email'].casefold()):
            data['supplier_id']=str(supplier.id);break
    for line in data['lines']:
        matched=next((p for p in products if (line['sku'] and p.sku.casefold()==line['sku'].casefold()) or p.name.casefold()==line['name'].casefold()),None)
        if matched:
            line['product_id']=str(matched.id)
            line['match']='Matched SKU/name — confirm it is the same stock unit.'
        else:
            likely=max(products,key=lambda p:SequenceMatcher(None,p.name.casefold(),line['name'].casefold()).ratio(),default=None)
            line['match']=f'Possible match: {likely.name}. Select it if correct.' if likely and SequenceMatcher(None,likely.name.casefold(),line['name'].casefold()).ratio()>.65 else 'New product — review name, SKU, category and selling price.'
            if not line['sku']: line['sku']='IMP-'+uuid4().hex[:8].upper()
        if matched:
            line['sku']=matched.sku;line['category']=matched.category;line['unit']=matched.unit
            line['price']=f'{matched.price_cents/100:.2f}'
        line['location_id']=''
    return data


def create_import(actor, text, source_name, source_key=None):
    try:
        actor=lock_store(actor,True)
        if not text.strip() or len(text)>100_000:
            raise DomainError('No readable text found. Try a sharper photo, text PDF, or paste the email content.')
        digest=hashlib.sha256(re.sub(r'\s+',' ',text).strip().encode()).hexdigest()
        existing=db.session.scalar(select(DocumentImport).where(DocumentImport.store_id==actor.store_id,DocumentImport.source_hash==digest))
        if existing:
            db.session.commit();return existing,False
        data=match_suggestions(actor.store_id,parse_text(text))
        draft=DocumentImport(store_id=actor.store_id,source_name=source_name[:200],source_hash=digest,
            source_text=text,data=data,created_by=actor.id,source_key=source_key)
        db.session.add(draft);db.session.commit()
        return draft,True
    except Exception:
        db.session.rollback();raise


def save_review(actor, ident, form):
    try:
        actor=lock_store(actor,True)
        draft=scoped(DocumentImport,ident,actor.store_id)
        if draft.status not in ('draft','reviewed'):
            raise DomainError('This import has already been finalized.')
        if whole(form.get('version'))!=draft.version:
            raise DomainError('This review changed in another tab. Reload before editing.')
        metadata={}
        limits={'supplier_name':100,'email':150,'phone':60,'address':500,'reference':100,
            'document_date':60,'currency':3,'notes':1000}
        for key,limit in limits.items():
            metadata[key]=bounded(form.get(key),limit,key.replace('_',' ').title(),key in ('supplier_name','currency'))
        metadata['currency']=metadata['currency'].upper()
        if metadata['currency']!='USD':
            raise DomainError('This store uses USD. Convert unit costs to USD and note the source currency before confirming.')
        for key in ('subtotal','tax','shipping','discount','total'):
            value=form.get(key,'').strip()
            metadata[key]=f'{money_cents(value,key)/100:.2f}' if value else ''
        supplier_id=form.get('supplier_id','').strip()
        if supplier_id:
            scoped(Supplier,whole(supplier_id,1),actor.store_id,True)
        elif not metadata['supplier_name']:
            raise DomainError('Enter the new supplier name.')
        keys=form.getlist('line_key')
        if not 1<=len(keys)<=100 or len(set(keys))!=len(keys):
            raise DomainError('Keep between 1 and 100 distinct product lines.')
        lines=[]
        for key in keys:
            if not re.fullmatch(r'\d{1,5}',key): raise DomainError('Invalid product row.')
            def get(field): return form.get(f'line_{key}_{field}','').strip()
            location=whole(get('location_id'),1)
            scoped(Location,location,actor.store_id,True)
            product_id=get('product_id')
            if product_id:
                product=scoped(Product,whole(product_id,1),actor.store_id,True)
                name,sku,category,unit,price=product.name,product.sku,product.category,product.unit,product.price_cents
            else:
                name=bounded(get('name'),120,'Product name')
                sku=bounded(get('sku'),60,'SKU')
                if not re.fullmatch(r'[A-Za-z0-9_.-]{1,60}',sku): raise DomainError('New product SKU uses letters, digits, dots, underscores or hyphens.')
                if db.session.scalar(select(Product.id).where(Product.store_id==actor.store_id,Product.sku==sku)):
                    raise DomainError(f'SKU {sku} exists. Select its existing product, or restore an archived product, instead of creating another.')
                category=bounded(get('category'),60,'Category')
                unit=bounded(get('unit'),30,'Unit')
                price=money_cents(get('price'),'Selling price for '+name)
            lines.append(dict(product_id=str(product_id),name=name,sku=sku,category=category,unit=unit,
                quantity=whole(get('quantity'),1),cost_cents=money_cents(get('cost')),cost=get('cost'),
                price_cents=price,price=f'{price/100:.2f}',location_id=location,
                description=bounded(get('description'),1000,'Description',False),reorder_level=whole(get('reorder_level') or '0')))
        new_skus=[line['sku'] for line in lines if not line['product_id']]
        if len(set(new_skus))!=len(new_skus):
            raise DomainError('New SKUs must be unique. Combine duplicate new-product rows into one quantity.')
        old=draft.data
        draft.data=dict(metadata=metadata,supplier_id=supplier_id,lines=lines,
            unparsed=old.get('unparsed',[]),warnings=old.get('warnings',[]),update_supplier=form.get('update_supplier')=='yes')
        draft.status='reviewed';draft.version+=1
        db.session.commit();return draft
    except Exception:
        db.session.rollback();raise


def prepare_records(actor,draft):
    data=draft.data;metadata=data['metadata']
    if draft.status!='reviewed': raise DomainError('Review and save every line before final confirmation.')
    if data.get('supplier_id'):
        supplier=scoped(Supplier,int(data['supplier_id']),actor.store_id,True)
        if data.get('update_supplier'):
            supplier.email=metadata['email'];supplier.phone=metadata['phone'];supplier.address=metadata['address']
            supplier.contact=metadata['email'] or metadata['phone']
    else:
        if db.session.scalar(select(Supplier.id).where(Supplier.store_id==actor.store_id, Supplier.name.ilike(metadata['supplier_name']),Supplier.archived.is_(False))):
            raise DomainError('A supplier with this name already exists. Select that supplier in the review.')
        # Do not silently merge suppliers based on approximate names.
        supplier=Supplier(store_id=actor.store_id,name=metadata['supplier_name'],email=metadata['email'],
            phone=metadata['phone'],address=metadata['address'],contact=metadata['email'] or metadata['phone'])
        db.session.add(supplier);db.session.flush()
    reference=metadata['reference'].strip().casefold()
    if reference:
        dedupe=f'{supplier.id}:{reference}'
        duplicate=db.session.scalar(select(DocumentImport).where(DocumentImport.store_id==actor.store_id,
            DocumentImport.dedupe_key==dedupe,DocumentImport.id!=draft.id))
        if duplicate:
            raise DomainError(f'This supplier/reference was already finalized as import #{duplicate.id}. Open that import/order instead.')
        draft.dedupe_key=dedupe
    resolved=[]
    for line in data['lines']:
        scoped(Location,int(line['location_id']),actor.store_id,True)
        if line['product_id']:
            product=scoped(Product,int(line['product_id']),actor.store_id,True)
        else:
            product=Product(store_id=actor.store_id,supplier_id=supplier.id,name=line['name'],sku=line['sku'],
                category=line['category'],unit=line['unit'],description=line.get('description',''),
                cost_cents=line['cost_cents'],price_cents=line['price_cents'],reorder_level=line['reorder_level'])
            db.session.add(product);db.session.flush()
        resolved.append((product,line))
    draft.supplier_id=supplier.id
    return supplier,resolved


def receive_document(actor,op,payload):
    from .inventory import move,quantity
    draft=scoped(DocumentImport,whole(payload['draft_id'],1),actor.store_id)
    if whole(payload['version'])!=draft.version: raise DomainError('Review changed; reload the confirmation.')
    supplier,lines=prepare_records(actor,draft)
    grouped={}
    for product,line in lines:
        pair=(product.id,int(line['location_id']))
        if pair not in grouped: grouped[pair]=[product,0]
        grouped[pair][1]+=line['quantity']
    for (pid,location),(product,qty) in sorted(grouped.items()):
        move(actor,op,product,location,qty,f'Import #{draft.id} · {supplier.name} · {draft.data["metadata"]["reference"]}', 'document_receipt')
    draft.status='received';draft.finalized_at=now()
    return {'draft_id':draft.id,'lines':len(lines)}


def create_document_order(actor,ident,version):
    try:
        actor=lock_store(actor,True)
        draft=scoped(DocumentImport,ident,actor.store_id)
        if draft.status=='ordered':
            db.session.commit();return draft.order_id
        if whole(version)!=draft.version: raise DomainError('Review changed; reload the confirmation.')
        supplier,lines=prepare_records(actor,draft)
        grouped={}
        for product,line in lines:
            if product.id in grouped:
                previous=grouped[product.id]
                if previous['location_id']!=line['location_id'] or previous['cost_cents']!=line['cost_cents']:
                    raise DomainError('Combine duplicate product lines with one receiving location and unit cost before saving an order.')
                previous['quantity']+=line['quantity']
            else: grouped[product.id]=dict(line)
        order=PurchaseOrder(store_id=actor.store_id,supplier_id=supplier.id,created_by=actor.id)
        db.session.add(order);db.session.flush()
        for pid,line in grouped.items():
            db.session.add(PurchaseOrderItem(store_id=actor.store_id,order_id=order.id,product_id=pid,
                destination_id=line['location_id'],quantity=line['quantity'],cost_cents=line['cost_cents']))
        draft.order_id=order.id;draft.status='ordered';draft.finalized_at=now()
        db.session.commit();return order.id
    except Exception:
        db.session.rollback();raise
