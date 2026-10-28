from io import BytesIO
import re
from sqlalchemy import select
from app.extensions import db
from app.models import Product,Sale,StockMovement,User
from app.services.inventory import quantity


def test_health_and_login_required(client):
    assert client.get('/health').json['status']=='ok'
    for path in ['/','/products','/scan','/orders','/exports/inventory.csv']:
        assert client.get(path).status_code==302
    assert client.post('/login',data={'email':'missing@test.test','password':'wrong'}).status_code==200


ROUTES=['/','/products','/products/new','/products/1','/products/1/edit','/products/1/label','/products/1/qr.png','/products/1/photo','/manage/suppliers','/manage/locations','/manage/staff','/locations','/scan','/scan?mode=sale','/inventory/sale?product_id=1','/inventory/receipt?product_id=1','/inventory/transfer?product_id=1','/refills','/counts','/reorder','/orders','/exports/inventory.csv','/exports/sales.csv','/exports/reorder.csv']

def test_all_pages_render(signed_in):
    for path in ROUTES:
        response=signed_in.get(path)
        assert response.status_code==200,path


def test_staff_and_cross_store_boundaries(client):
    client.post('/login',data={'email':'staff@test.test','password':'test-password'})
    for path in ['/products/new','/products/1/edit','/manage/suppliers','/manage/locations','/manage/staff','/exports/inventory.csv','/exports/sales.csv','/exports/reorder.csv']:
        assert client.get(path).status_code==403,path
    for path in ['/products/1/edit','/products/1/photo','/products/1/archive','/reorder','/refills']:
        assert client.post(path,data={}).status_code==403,path
    for path in ['/products/2','/products/2/photo','/products/2/qr.png','/products/2/label','/inventory/sale?product_id=2']:
        assert client.get(path).status_code==404,path
    response=client.get('/products/1')
    assert b'$3.50' not in response.data and b'$5.50' not in response.data


def test_scan_does_not_mutate_and_manual_qr_equivalence(signed_in,product):
    before=quantity(1,1)
    manual=signed_in.post('/scan',data={'mode':'sale','code':'OAT-001'})
    qr=signed_in.post('/scan',data={'mode':'sale','code':product.qr_payload})
    assert manual.location==qr.location
    assert quantity(1,1)==before
    assert signed_in.post('/scan',data={'mode':'sale','code':'https://evil.test'}).status_code==200
    assert quantity(1,1)==before


def test_review_confirm_retry(signed_in):
    data={'product_id':'1','location_id':'1','quantity':'2','reason':'','token':'test_sale_submit_000001'}
    response=signed_in.post('/inventory/sale',data=data)
    assert b'Confirm sale' in response.data and quantity(1,1)==8
    data['confirm']='yes'
    assert signed_in.post('/inventory/sale',data=data).status_code==302
    assert signed_in.post('/inventory/sale',data=data).status_code==302
    assert quantity(1,1)==6


def test_catalog_edit_does_not_reset_stock(signed_in,product):
    token=product.qr_token
    response=signed_in.post('/products/1/edit',data=dict(name='New name',sku='OAT-001',category='Milk',unit='carton',supplier_id=1,cost='3.50',price='6.00',reorder_level='5',description='<script>bad</script>'))
    assert response.status_code==302
    assert quantity(1,1)==8
    assert db.session.get(Product,1).qr_token==token
    assert b'&lt;script&gt;' in signed_in.get('/products/1').data


def test_image_upload_failure_no_stock_change(signed_in):
    response=signed_in.post('/products/1/photo',data={'photo':(BytesIO(b'<html>bad</html>'),'photo.png')},content_type='multipart/form-data')
    assert response.status_code==302 and quantity(1,1)==8
    assert db.session.get(Product,1).image_key is None


def test_csrf_enforced(app,client):
    app.config['WTF_CSRF_ENABLED']=True
    assert client.post('/login',data={'email':'owner@test.test','password':'test-password'}).status_code==400
    response=client.get('/login')
    token=re.search(rb'name="csrf_token" value="([^"]+)"',response.data).group(1).decode()
    assert client.post('/login',data={'email':'owner@test.test','password':'test-password','csrf_token':token}).status_code==302
    assert client.post('/logout').status_code==400


def test_negative_money_and_duplicate_catalog(signed_in):
    data=dict(name='Invalid',sku='OAT-001',category='Milk',unit='carton',supplier_id=1,cost='-1',price='2.00',reorder_level='5',description='')
    assert signed_in.post('/products/new',data=data).status_code==200
    data['cost']='1.00'
    assert signed_in.post('/products/new',data=data).status_code==200
    assert quantity(1,1)==8


def test_empty_new_product_no_movement_and_opening_once(signed_in):
    data=dict(name='New',sku='NEW',category='Milk',unit='carton',supplier_id=1,cost='1.00',price='2.00',reorder_level='5',description='',opening_quantity='0',token='create_product_token00001')
    response=signed_in.post('/products/new',data=data)
    assert response.status_code==302
    p=db.session.scalar(select(Product).where(Product.sku=='NEW'))
    assert quantity(1,p.id)==0
    assert db.session.scalar(select(StockMovement.id).where(StockMovement.product_id==p.id)) is None
    data.update(sku='OPEN',opening_quantity='7',location_id='1',token='create_product_token00002')
    assert signed_in.post('/products/new',data=data).status_code==302
    p=db.session.scalar(select(Product).where(Product.sku=='OPEN'))
    assert quantity(1,p.id)==7


def test_foreign_order_count_export_and_location_requests(signed_in):
    # Other-store account has no objects in the signed-in store; IDs must be scoped.
    assert signed_in.get('/orders/999').status_code==404
    assert signed_in.get('/orders/999/export.csv').status_code==404
    assert signed_in.post('/counts/999/approve',data={'token':'test_approval_token01'}).status_code==404
    assert signed_in.get('/products?location=3').status_code==404
    assert signed_in.get('/products?location=abc').status_code==400


def test_staff_direct_count_order_and_export_denials(client,owner,product):
    from app.services.orders import create_drafts
    product.reorder_level=20;db.session.commit()
    order_id=create_drafts(owner,2,{1})[0]
    client.post('/login',data={'email':'staff@test.test','password':'test-password'})
    for action in ['approve','edit','cancel']:
        assert client.post(f'/orders/{order_id}',data={'action':action}).status_code==403
    assert client.get(f'/orders/{order_id}/export.csv').status_code==403
    assert client.post('/counts/1/approve',data={}).status_code==403


def test_location_archive_stock_and_rule_guard(signed_in):
    response=signed_in.post('/locations/1/archive',follow_redirects=True)
    assert b'Move stock and resolve' in response.data


def test_product_image_survives_new_application(app,signed_in,tmp_path):
    from PIL import Image
    from app import create_app
    image=BytesIO();Image.new('RGB',(80,60),'green').save(image,'PNG');image.seek(0)
    signed_in.post('/products/1/photo',data={'photo':(image,'green.png')},content_type='multipart/form-data')
    before=signed_in.get('/products/1/photo').data
    restarted=create_app({**app.config,'TESTING':True})
    with restarted.test_client() as client:
        client.post('/login',data={'email':'owner@test.test','password':'test-password'})
        response=client.get('/products/1/photo')
        assert response.status_code==200 and response.data==before
