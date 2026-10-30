from decimal import Decimal
from pathlib import Path
from io import BytesIO
from uuid import uuid4
import pytest
from PIL import Image
from sqlalchemy import select
from werkzeug.datastructures import MultiDict
from app.extensions import db
from app.models import DocumentImport,Product,StockMovement,User
from app.services.document_reader import extract_document,parse_text
from app.services.document_checks import inspect_document
from app.services.documents import create_import,save_review
from app.services.inventory import execute,quantity,reconciliation
from app.services.common import DomainError

FIXTURE=Path(__file__).parent/'fixtures'/'invoice_test_1042.jpg'
EXPECTED=[('OAT-001','Oat Milk 1L','12','3.50','42.00'),('RIC-002','Rice 1kg','8','4.25','34.00'),('BEA-003','Black Beans 400g','10','1.40','14.00')]


def test_actual_failed_invoice_image_extracts_exact_fields_with_local_ml():
    text=extract_document(FIXTURE.read_bytes(),FIXTURE.name)
    data=parse_text(text)
    assert [(r['sku'],r['name'],r['quantity'],r['cost'],r['source_total']) for r in data['lines']]==EXPECTED
    assert data['metadata']['supplier_name']=='Midwest Demo Supplies'
    assert data['metadata']['reference']=='TEST-1042'
    assert data['metadata']['document_date']=='2026-10-29'
    assert data['metadata']['total']=='90.00'
    assert data['validation']['balanced'] and data['validation']['items_cents']==9000
    assert 'RapidOCR' in data['extraction']['engine']


@pytest.mark.parametrize('scale,angle',[(.75,0),(1,3)])
def test_invoice_layout_handles_resize_and_mild_tilt(scale,angle):
    with Image.open(FIXTURE) as image:
        image=image.resize((int(image.width*scale),int(image.height*scale)))
        if angle: image=image.rotate(angle,expand=True,fillcolor='white')
        buffer=BytesIO();image.save(buffer,'PNG')
    data=parse_text(extract_document(buffer.getvalue(),'variant.png'))
    assert [(r['sku'],r['quantity'],r['cost']) for r in data['lines']]==[(s,q,c) for s,n,q,c,t in EXPECTED]
    assert data['metadata']['reference']=='TEST-1042' and data['validation']['balanced']


def test_delivery_fee_cannot_become_an_inventory_product():
    data=parse_text('Supplier: Midwest Demo Supplies\nInvoice: TEST-1042\nDelivery: $0.00\nTOTAL: $90.00')
    assert data['lines']==[]
    assert data['validation']['errors']


def test_wrong_line_and_document_totals_are_blocking_errors():
    result=inspect_document({'supplier_name':'Midwest','subtotal':'90.00','total':'90.00'},
        [{'name':'Delivery:','quantity':13,'cost_cents':0}])
    assert result['errors'] and not result['balanced']
    result=inspect_document({'supplier_name':'Midwest','total':'42.00'},
        [{'quantity':12,'cost_cents':350,'source_total':'34.00'}])
    assert any('printed line total' in error for error in result['errors'])


def test_cannot_save_a_zero_cost_misread_as_a_90_dollar_receipt(app,owner):
    text='Supplier: Midwest Demo Supplies\nInvoice: TEST-1042\nDescription,Qty,Unit cost\nDelivery,13,0.00\nTotal: 90.00'
    draft,_=create_import(owner,text,'broken.txt')
    form=MultiDict({'version':'0','supplier_name':'Midwest Demo Supplies','currency':'USD','reference':'TEST-1042',
        'total':'90.00','line_key':'0','line_0_product_id':'1','line_0_quantity':'13','line_0_cost':'0.00','line_0_location_id':'1'})
    with pytest.raises(DomainError,match='not document total'):
        save_review(owner,draft.id,form)
    assert quantity(1,1)==8 and db.session.get(DocumentImport,draft.id).status=='draft'


def test_reviewed_legacy_bad_totals_cannot_bypass_finalization(app,owner):
    draft,_=create_import(owner,'Supplier: Midwest Demo Supplies\nOat milk 13 0.00','old.txt')
    draft.status='reviewed'
    draft.data={'metadata':{'supplier_name':'Midwest Demo Supplies','subtotal':'90.00','total':'90.00'},
        'supplier_id':'1','lines':[{'product_id':'1','quantity':13,'cost_cents':0,'location_id':1}]}
    db.session.commit()
    with pytest.raises(DomainError):
        execute(owner,'document_receipt',{'draft_id':draft.id,'version':draft.version},uuid4().hex)
    assert quantity(1,1)==8


def test_reversal_appends_once_and_preserves_original_receipt(app,owner):
    from test_business_workflows import ready_import
    draft=ready_import(owner)
    execute(owner,'document_receipt',{'draft_id':draft.id,'version':draft.version},uuid4().hex)
    original_movements=db.session.scalar(select(db.func.count()).select_from(StockMovement))
    key=uuid4().hex;payload={'draft_id':draft.id,'reason':'OCR mistake verified against invoice'}
    execute(owner,'document_reversal',payload,key)
    assert quantity(1,1)==8
    tea=db.session.scalar(select(Product).where(Product.sku=='TEA-NEW'))
    assert quantity(1,tea.id)==0
    assert execute(owner,'document_reversal',payload,key)['duplicate']
    assert db.session.scalar(select(db.func.count()).select_from(StockMovement))==original_movements+2
    assert db.session.get(DocumentImport,draft.id).status=='received' and draft.data['reversal']
    assert reconciliation(1)==[]


def test_staff_cannot_reverse_a_receipt(app,owner):
    from test_business_workflows import ready_import
    draft=ready_import(owner)
    execute(owner,'document_receipt',{'draft_id':draft.id,'version':draft.version},uuid4().hex)
    with pytest.raises(DomainError): execute(db.session.get(User,2),'document_reversal',{'draft_id':draft.id,'reason':'Bad reading'},uuid4().hex)
    assert quantity(1,1)==20


def test_reread_saved_failed_image_prepares_corrected_draft_only(app,owner,signed_in):
    from flask import current_app
    directory=Path(current_app.config['UPLOAD_DIR'])/'documents';directory.mkdir()
    (directory/'failed.jpg').write_bytes(FIXTURE.read_bytes())
    old,_=create_import(owner,'Supplier: Invoice:\nDelivery 13 0.00','invoice.jpg','failed.jpg')
    response=signed_in.post(f'/imports/{old.id}/reread')
    assert response.status_code==302
    corrected=db.session.scalar(select(DocumentImport).where(DocumentImport.id!=old.id))
    assert corrected.data['reprocessed_from']==old.id
    assert corrected.data['metadata']['reference']=='TEST-1042'
    assert len(corrected.data['lines'])==3 and corrected.data['validation']['balanced']
    assert quantity(1,1)==8
    page=signed_in.get(response.location)
    assert page.status_code==200 and b'Midwest Demo Supplies' in page.data
    signed_in.post(f'/imports/{old.id}/reread')
    assert db.session.scalar(select(db.func.count()).select_from(DocumentImport))==2


def test_replacement_requires_reversal_and_releases_invoice_reference(app,owner):
    from test_business_workflows import ready_import,TEXT,review_form
    old=ready_import(owner)
    execute(owner,'document_receipt',{'draft_id':old.id,'version':old.version},uuid4().hex)
    replacement,_=create_import(owner,TEXT+'\nCorrected review','replacement.txt')
    replacement.data={**replacement.data,'reprocessed_from':old.id};db.session.commit()
    form=review_form(replacement)
    tea=db.session.scalar(select(Product).where(Product.sku=='TEA-NEW'))
    form['line_1_product_id']=str(tea.id)
    save_review(owner,replacement.id,form)
    payload={'draft_id':replacement.id,'version':replacement.version}
    with pytest.raises(DomainError,match='Reverse its incorrect receipt'):
        execute(owner,'document_receipt',payload,uuid4().hex)
    execute(owner,'document_reversal',{'draft_id':old.id,'reason':'Correct the reviewed invoice'},uuid4().hex)
    assert old.dedupe_key is None
    execute(owner,'document_receipt',payload,uuid4().hex)
    assert quantity(1,1)==20 and reconciliation(1)==[]


def test_reversal_with_missing_stock_rolls_back_every_line(app,owner):
    from test_business_workflows import ready_import
    draft=ready_import(owner)
    execute(owner,'document_receipt',{'draft_id':draft.id,'version':draft.version},uuid4().hex)
    tea=db.session.scalar(select(Product).where(Product.sku=='TEA-NEW'))
    execute(owner,'sale',{'product_id':tea.id,'location_id':2,'quantity':1},uuid4().hex)
    with pytest.raises(DomainError):
        execute(owner,'document_reversal',{'draft_id':draft.id,'reason':'Read error'},uuid4().hex)
    assert quantity(1,1)==20 and quantity(1,tea.id)==5
    assert not db.session.get(DocumentImport,draft.id).data.get('reversal')
    assert reconciliation(1)==[]


def test_actual_invoice_scanned_pdf_preserves_table():
    with Image.open(FIXTURE) as image:
        buffer=BytesIO();image.convert('RGB').save(buffer,'PDF',resolution=120)
    data=parse_text(extract_document(buffer.getvalue(),'invoice.pdf'))
    assert [(r['sku'],r['quantity'],r['cost']) for r in data['lines']]==[(s,q,c) for s,n,q,c,t in EXPECTED]
    assert data['metadata']['supplier_name']=='Midwest Demo Supplies' and data['validation']['balanced']


def test_native_pdf_multicolumn_fields_and_table():
    from reportlab.pdfgen.canvas import Canvas
    buffer=BytesIO();canvas=Canvas(buffer,pagesize=(700,850))
    for x,y,text in [(30,800,'Supplier:'),(420,800,'Invoice:'),(30,780,'Midwest Demo Supplies'),(420,780,'TEST-1042'),
        (30,730,'SKU'),(165,730,'Description'),(390,730,'Qty'),(465,730,'Unit cost'),(565,730,'Line total')]:
        canvas.drawString(x,y,text)
    for i,(sku,name,qty,cost,total) in enumerate(EXPECTED):
        for x,value in zip([30,165,390,465,565],[sku,name,qty,'$'+cost,'$'+total]): canvas.drawString(x,700-i*30,value)
    canvas.drawString(420,570,'Subtotal:');canvas.drawString(565,570,'$90.00')
    canvas.drawString(420,540,'TOTAL:');canvas.drawString(565,540,'$90.00');canvas.save()
    data=parse_text(extract_document(buffer.getvalue(),'native.pdf'))
    assert [(r['sku'],r['quantity'],r['cost']) for r in data['lines']]==[(s,q,c) for s,n,q,c,t in EXPECTED]
    assert data['metadata']['supplier_name']=='Midwest Demo Supplies'
    assert data['metadata']['reference']=='TEST-1042' and data['validation']['balanced']
