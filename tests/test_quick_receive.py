from uuid import uuid4
from sqlalchemy import select,func
from app.extensions import db
from app.models import DocumentImport,Product,Supplier,StockMovement,User
from app.services.documents import create_import
from app.services.inventory import quantity,reconciliation,execute
from app.services.common import DomainError
import pytest

TEXT='Supplier: Midwest Supplies\nInvoice: QUICK-1\nSKU,Description,Qty,Unit cost,Line total\nOAT-001,Oat Milk 1L,12,3.50,42.00\nRIC-002,Rice 1kg,8,4.25,34.00\nBEA-003,Black Beans 400g,10,1.40,14.00\nTotal: 90.00'


def quick_form(draft):
    data={'mode':'quick','version':str(draft.version),'token':uuid4().hex,'destination':'2','confirmed':'yes'}
    data['line_key']=[str(i) for i in range(len(draft.data['lines']))]
    for i,line in enumerate(draft.data['lines']):
        for key in ['name','quantity','cost','product_id','category','unit']:
            data[f'line_{i}_{key}']=line.get(key,'')
    return data


def test_owner_adds_complete_bill_without_company_or_catalog_fields(signed_in,owner):
    draft,_=create_import(owner,TEXT,'bill.txt')
    response=signed_in.get(f'/imports/{draft.id}')
    assert b'Check your items' in response.data and b'name="supplier_name"' not in response.data
    assert b'name="line_1_price"' not in response.data
    form=quick_form(draft)
    response=signed_in.post(f'/imports/{draft.id}',data=form)
    assert response.status_code==302
    assert quantity(1,1)==20
    rice=db.session.scalar(select(Product).where(Product.sku=='RIC-002'))
    assert quantity(1,rice.id)==8 and rice.cost_cents==425 and rice.price_cents==0
    catalog=signed_in.get('/products?view=cards')
    assert catalog.status_code==200 and b'Set selling price' in catalog.data
    table=signed_in.get('/products?view=table')
    assert table.status_code==200 and b'Set selling price' in table.data
    assert db.session.get(DocumentImport,draft.id).data['metadata']['supplier_name']=='Midwest Supplies'
    assert reconciliation(1)==[]
    before=db.session.scalar(select(func.count()).select_from(StockMovement))
    signed_in.post(f'/imports/{draft.id}',data=form)
    assert db.session.scalar(select(func.count()).select_from(StockMovement))==before
    with pytest.raises(DomainError,match='selling price'):
        execute(owner,'sale',{'product_id':rice.id,'quantity':1,'location_id':2},uuid4().hex)
    assert quantity(1,rice.id)==8


def test_worker_uploads_checks_receives_without_owner_setup(client,app):
    staff=db.session.get(User,2)
    client.post('/login',data={'email':'staff@test.test','password':'test-password'})
    response=client.post('/imports',data={'source_text':TEXT})
    assert response.status_code==302
    draft=db.session.scalar(select(DocumentImport))
    assert draft.created_by==staff.id
    assert client.get(response.location).status_code==200
    assert b'name="supplier_name"' not in client.get(response.location+'?advanced=1').data
    assert client.post(f'/imports/{draft.id}',data={'supplier_name':'Injected'}).status_code==403
    form=quick_form(draft)
    form['supplier_name']='Injected company';form['update_supplier']='yes';form['line_0_price']='0.01'
    assert client.post(f'/imports/{draft.id}',data=form).status_code==302
    draft=db.session.get(DocumentImport,draft.id)
    assert draft.status=='received' and quantity(1,1)==20
    assert db.session.get(Product,1).price_cents==550
    assert draft.data['metadata']['supplier_name']=='Midwest Supplies' and not draft.data['update_supplier']
    assert client.get(f'/imports/{draft.id}/reverse').status_code==403
    assert client.get(f'/imports/{draft.id}/confirm').status_code==403


def test_unknown_supplier_is_not_required(signed_in,owner):
    draft,_=create_import(owner,'Oat milk 2 3.50 7.00\nTotal: 7.00','bill.txt')
    assert signed_in.post(f'/imports/{draft.id}',data=quick_form(draft)).status_code==302
    assert db.session.get(DocumentImport,draft.id).status=='received'
    assert db.session.scalar(select(Supplier).where(Supplier.name=='Unspecified supplier'))


def test_worker_cannot_open_or_mutate_another_workers_document(client,owner):
    draft,_=create_import(owner,TEXT,'bill.txt')
    client.post('/login',data={'email':'staff@test.test','password':'test-password'})
    for path in [f'/imports/{draft.id}',f'/imports/{draft.id}/source']:
        assert client.get(path).status_code==404
    assert client.post(f'/imports/{draft.id}',data=quick_form(draft)).status_code==404
    assert client.post('/imports',data={'source_text':TEXT}).status_code==200
    assert db.session.scalar(select(func.count()).select_from(DocumentImport))==1
    assert quantity(1,1)==8


def test_quick_receive_preserves_totals_and_is_all_or_nothing(signed_in,owner):
    draft,_=create_import(owner,TEXT,'bill.txt')
    form=quick_form(draft);form['line_1_quantity']='9'
    response=signed_in.post(f'/imports/{draft.id}',data=form)
    assert response.status_code==200
    assert b'printed line total' in response.data and b'90.00' in response.data
    assert quantity(1,1)==8 and db.session.get(DocumentImport,draft.id).status=='draft'
    assert not db.session.scalar(select(Product).where(Product.sku=='RIC-002'))
    removed=quick_form(draft);removed['line_key']=['1','2']
    response=signed_in.post(f'/imports/{draft.id}',data=removed)
    assert response.status_code==200 and b'name="line_1_name"' in response.data
    assert b'name="line_0_name"' not in response.data
    form=quick_form(draft);form.pop('confirmed')
    signed_in.post(f'/imports/{draft.id}',data=form)
    assert quantity(1,1)==8
    form=quick_form(draft);form['destination']='3'
    signed_in.post(f'/imports/{draft.id}',data=form)
    assert quantity(1,1)==8
