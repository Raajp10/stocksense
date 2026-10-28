from concurrent.futures import ThreadPoolExecutor
from datetime import date,timedelta
from io import BytesIO
from uuid import uuid4
import pytest
from PIL import Image
from sqlalchemy import select,func
from app.extensions import db
from app.models import *
from app.services.common import DomainError
from app.services.inventory import execute, quantity, submit_count, reconciliation
from app.services.reorder import calculate,recommendations,utc_bounds,shelf_refills
from app.services.orders import create_drafts,change_order
from app.services.scan import resolve
from app.services.media import save_image
from app.services.reporting import report
from app.routes import csv_safe


def token(): return uuid4().hex


@pytest.mark.parametrize('args,expected',[
 ((84,14,5,5,8,0),(6,30,22)),((84,14,5,5,8,10),(6,30,12)),
 ((0,14,5,10,3,0),(0,10,7)),((0,0,5,10,3,0),(0,10,7)),
 ((1,14,5,0,0,0),(1/14,1,1)),((0,14,5,5,5,0),(0,5,0))])
def test_reorder_arithmetic(args,expected):
    result=calculate(*args)
    assert (result['average'],result['target'],result['suggested'])==expected
    if not args[0]: assert result['days_remaining'] is None


def test_demo_sequence_and_duplicate(app,owner,product):
    payload=dict(product_id=product.id,location_id=1,quantity=2)
    key=token()
    execute(owner,'sale',payload,key)
    assert execute(owner,'sale',payload,key)['duplicate']
    assert (quantity(1,product.id,1),quantity(1,product.id,2))==(1,5)
    with pytest.raises(DomainError,match='different action'):
        execute(owner,'sale',dict(payload,quantity=1),key)
    execute(owner,'transfer',dict(product_id=product.id,location_id=2,destination_id=1,quantity=4),token())
    assert (quantity(1,product.id,1),quantity(1,product.id,2))==(5,1)
    execute(owner,'receipt',dict(product_id=product.id,location_id=2,quantity=24,reason='Supplier delivery D-24'),token())
    assert (quantity(1,product.id,1),quantity(1,product.id,2),quantity(1,product.id))==(5,25,30)
    assert db.session.scalar(select(func.count()).select_from(Sale))==1
    assert reconciliation(1)==[]


@pytest.mark.parametrize('kind,payload',[
 ('sale',dict(product_id=1,location_id=1,quantity=4)),
 ('sale',dict(product_id=1,location_id=3,quantity=1)),
 ('sale',dict(product_id=2,location_id=1,quantity=1)),
 ('transfer',dict(product_id=1,location_id=1,destination_id=1,quantity=1)),
 ('transfer',dict(product_id=1,location_id=1,destination_id=3,quantity=1)),
 ('sale',dict(product_id=1,location_id=1,quantity=0)),
 ('sale',dict(product_id=1,location_id=1,quantity='1.5')),
 ('receipt',dict(product_id=1,location_id=1,quantity=1,reason=''))])
def test_invalid_operations_rollback(app,owner,kind,payload):
    count=db.session.scalar(select(func.count()).select_from(Operation))
    with pytest.raises(DomainError): execute(owner,kind,payload,token())
    assert quantity(1,1)==8
    assert db.session.scalar(select(func.count()).select_from(Operation))==count
    assert reconciliation(1)==[]


def test_transfer_failure_rolls_back_both_legs(app,owner,monkeypatch):
    import app.services.inventory as inventory
    original=inventory.move
    def fail_second(actor,op,product,location,delta,reason,kind=None):
        if delta>0: raise RuntimeError('Injected failure')
        original(actor,op,product,location,delta,reason,kind)
    monkeypatch.setattr(inventory,'move',fail_second)
    with pytest.raises(RuntimeError): execute(owner,'transfer',dict(product_id=1,location_id=2,destination_id=1,quantity=4),token())
    assert (quantity(1,1,1),quantity(1,1,2))==(3,5)
    assert reconciliation(1)==[]


def test_stale_count_and_success(app,owner):
    count=submit_count(owner,1,1,2,'Damaged carton found')
    execute(owner,'sale',dict(product_id=1,location_id=1,quantity=1),token())
    with pytest.raises(DomainError,match='Stock changed'): execute(owner,'adjustment',dict(count_id=count.id),token())
    fresh=submit_count(owner,1,1,1,'Recount after sale')
    execute(owner,'adjustment',dict(count_id=fresh.id),token())
    assert quantity(1,1,1)==1 and reconciliation(1)==[]


def test_staff_cannot_adjust_or_open(app):
    staff=db.session.get(User,2)
    with pytest.raises(DomainError): execute(staff,'opening',dict(product_id=1,location_id=1,quantity=5),token())
    count=submit_count(staff,1,1,0,'Counted empty')
    with pytest.raises(DomainError): execute(staff,'adjustment',dict(count_id=count.id),token())


def test_concurrent_sales_never_negative(app):
    def sell(_):
        with app.app_context():
            actor=db.session.get(User,1)
            try:
                execute(actor,'sale',dict(product_id=1,location_id=1,quantity=2),token())
                return True
            except DomainError:
                return False
            finally: db.session.remove()
    db.session.remove()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(sell,range(2)))
    assert sorted(results)==[False,True]
    assert quantity(1,1,1)==1
    assert reconciliation(1)==[]


def test_concurrent_transfers(app):
    def transfer(_):
        with app.app_context():
            try:
                execute(db.session.get(User,1),'transfer',dict(product_id=1,location_id=2,destination_id=1,quantity=4),token())
                return True
            except DomainError: return False
            finally: db.session.remove()
    db.session.remove()
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(transfer,range(2)))
    assert sorted(results)==[False,True]
    assert (quantity(1,1,1),quantity(1,1,2))==(7,1)
    assert reconciliation(1)==[]


def make_history(owner,product,today):
    product.created_at=utc_bounds(today-timedelta(days=40),today,'America/Chicago')[0]
    execute(owner,'receipt',dict(product_id=1,location_id=2,quantity=84,reason='History fixture'),token())
    for day in range(14,0,-1):
        result=execute(owner,'sale',dict(product_id=1,location_id=2,quantity=6),token())
        sale=db.session.scalar(select(Sale).where(Sale.operation_id==result['operation_id']))
        sale.effective_at=utc_bounds(today-timedelta(days=day),today,'America/Chicago')[0]+timedelta(hours=12)
        db.session.commit()


def test_completed_day_window_and_new_product(app,owner,product):
    today=date.today()
    make_history(owner,product,today)
    row=recommendations(1,today)[0]
    assert (row['sold'],row['days'],row['average'],row['suggested'])==(84,14,6,22)
    execute(owner,'sale',dict(product_id=1,location_id=1,quantity=1),token())
    assert recommendations(1,today)[0]['sold']==84
    product.created_at=utc_bounds(today-timedelta(days=2),today,'America/Chicago')[0]
    db.session.commit()
    assert recommendations(1,today)[0]['days']==2


def test_order_lifecycle_full_receipt_and_incoming(app,owner,product):
    make_history(owner,product,date.today())
    ids=create_drafts(owner,2,{1})
    order=db.session.get(PurchaseOrder,ids[0])
    assert order.items[0].quantity==22 and quantity(1,1)==8
    assert recommendations(1)[0]['incoming']==0
    change_order(owner,order.id,'approve')
    assert recommendations(1)[0]['suggested']==0 and quantity(1,1)==8
    key=token();execute(owner,'order_receipt',dict(order_id=order.id),key)
    assert execute(owner,'order_receipt',dict(order_id=order.id),key)['duplicate']
    with pytest.raises(DomainError): execute(owner,'order_receipt',dict(order_id=order.id),token())
    with pytest.raises(DomainError): change_order(owner,order.id,'cancel')
    assert quantity(1,1)==30 and reconciliation(1)==[]


def test_duplicate_draft_approval_recomputed(app,owner,product):
    make_history(owner,product,date.today())
    first=create_drafts(owner,2,{1})[0]
    second=create_drafts(owner,2,{1})[0]
    change_order(owner,first,'approve')
    with pytest.raises(DomainError,match='Demand'): change_order(owner,second,'approve')


def test_receipt_failure_rolls_back_all_lines(app,owner,product,monkeypatch):
    p=Product(store_id=1,supplier_id=1,sku='SECOND',name='Second',reorder_level=10,created_at=now()-timedelta(days=30))
    db.session.add(p);db.session.commit()
    product.reorder_level=20;db.session.commit()
    order_id=create_drafts(owner,2)[0];change_order(owner,order_id,'approve')
    import app.services.inventory as inventory
    original=inventory.move
    def fail(actor,op,product,location,delta,reason,kind=None):
        if product.sku=='SECOND': raise RuntimeError('Injected receipt failure')
        original(actor,op,product,location,delta,reason,kind)
    monkeypatch.setattr(inventory,'move',fail)
    with pytest.raises(RuntimeError): execute(owner,'order_receipt',dict(order_id=order_id),token())
    assert quantity(1,1)==8 and quantity(1,p.id)==0
    assert db.session.get(PurchaseOrder,order_id).status=='approved'
    assert reconciliation(1)==[]


def test_transfer_does_not_change_sales_or_reorder(app,owner):
    before=recommendations(1)[0]
    assert shelf_refills(1)[0]['suggested']==2
    execute(owner,'transfer',dict(product_id=1,location_id=2,destination_id=1,quantity=2),token())
    after=recommendations(1)[0]
    assert (before['stock'],before['sold'],before['suggested'])==(after['stock'],after['sold'],after['suggested'])
    assert shelf_refills(1)[0]['suggested']==0


def test_qr_store_scoping_and_stability(app,product):
    payload=product.qr_payload
    product.name='Changed';product.price_cents=999;db.session.commit()
    assert resolve(1,payload).id==product.id
    assert resolve(1,'OAT-001').id==product.id
    for invalid in ['https://evil.test', 'stocksense:v2:product:abc',db.session.get(Product,2).qr_payload]:
        with pytest.raises(DomainError): resolve(1,invalid)


def test_image_validation_and_normalization(app):
    image=Image.new('RGB',(1600,400),'red');data=BytesIO();image.save(data,'PNG');data.seek(0)
    key=save_image(data)
    from pathlib import Path
    with Image.open(Path(app.config['UPLOAD_DIR'])/key) as result:
        assert result.size==(1200,300) and result.format=='JPEG'
    for data in [b'<svg><script>alert(1)</script></svg>',b'garbage',b'x'*(5*1024*1024+1)]:
        with pytest.raises(DomainError): save_image(BytesIO(data))
    large=Image.new('1',(4100,4100));data=BytesIO();large.save(data,'PNG');data.seek(0)
    with pytest.raises(DomainError): save_image(data)


@pytest.mark.parametrize('text',['=HYPERLINK("x")',' +SUM(A1)','-1+2','@cmd','\tformula','\rformula','\nformula'])
def test_csv_formula_neutralization(text): assert csv_safe(text).startswith("'")


def test_report_snapshot_zero_sales_and_dst(app,owner,product):
    execute(owner,'sale',dict(product_id=1,location_id=1,quantity=2),token())
    product.price_cents=999;db.session.commit()
    result=report(1)
    assert result['revenue']==1100
    assert result['fastest'][0][1]==2
    lo,hi=utc_bounds(date(2026,3,8),date(2026,3,9),'America/Chicago')
    assert (hi-lo).total_seconds()==23*3600
    with pytest.raises(DomainError): report(1,'2026-12-31','2026-01-01')
    empty=report(1,'2020-01-01','2020-01-02')
    assert empty['units']==0 and len(empty['chart']['labels'])==2
