from io import BytesIO
import shutil
from uuid import uuid4
from email.message import EmailMessage
from werkzeug.datastructures import MultiDict
from sqlalchemy import select,func
from PIL import Image,ImageDraw
import pytest
from app.extensions import db
from app.models import Product,Supplier,DocumentImport,CountSession,User,PurchaseOrder,StockMovement
from app.services.common import DomainError
from app.services.document_reader import parse_text,extract_document
from app.services.documents import create_import,save_review,create_document_order
from app.services.inventory import execute,quantity,reconciliation
from app.services.stocktakes import create_session,record_counts,review_action
from app.services.orders import change_order

TEXT='''Supplier: Supplier
Email: orders@supplier.test
Phone: 312-555-1234
Address: 12 Main Street, Chicago IL
Invoice: INV-1042
Date: 2026-10-29
SKU,Description,Qty,Unit cost,Total
OAT-001,Oat milk,12,3.50,42.00
TEA-NEW,Green tea,6,2.00,12.00
Tax: 3.00
Total: 57.00
'''


def key(): return uuid4().hex


def review_form(draft):
    data=draft.data
    form=MultiDict({'version':str(draft.version),'supplier_id':'1',**data['metadata']})
    for i,line in enumerate(data['lines']):
        form.add('line_key',str(i))
        values=dict(line,location_id='2',price=line.get('price') or '4.00',reorder_level='5')
        for k,v in values.items(): form[f'line_{i}_{k}']=str(v)
    return form


def ready_import(owner,text=TEXT):
    draft,_=create_import(owner,text,'test receipt.txt')
    save_review(owner,draft.id,review_form(draft))
    return db.session.get(DocumentImport,draft.id)


def counted_form(session,quantity='2'):
    return MultiDict({'revision':str(len(session.events)),**{f'count_{line.id}':quantity for line in session.lines}})


def test_table_parse_supplier_and_amounts():
    data=parse_text(TEXT)
    assert data['metadata']['supplier_name']=='Supplier'
    assert data['metadata']['email']=='orders@supplier.test'
    assert data['metadata']['reference']=='INV-1042'
    assert data['metadata']['tax']=='3.00' and data['metadata']['total']=='57.00'
    assert [(line['sku'],line['quantity'],line['cost']) for line in data['lines']]==[('OAT-001','12','3.50'),('TEA-NEW','6','2.00')]


@pytest.mark.parametrize('row,expected',[
 ('Oat milk 12 3.50 42.00',('Oat milk','12','3.50')),
 ('12 Oat milk 3.50 42.00',('Oat milk','12','3.50')),
 ('12 x Oat milk @ $3.50',('Oat milk','12','3.50')),
 ('Oat milk\n12 x 3.50',('Oat milk','12','3.50')),
 ('Oat milk 12',('Oat milk','12','')),
 ('Oat milk 3.50',('Oat milk','','3.50'))])
def test_receipt_row_variants(row,expected):
    data=parse_text('Supplier: Example\n'+row)
    assert (data['lines'][0]['name'],data['lines'][0]['quantity'],data['lines'][0]['cost'])==expected


def test_saved_html_email_is_text_only():
    message=EmailMessage();message['From']='Midwest Dairy <orders@midwest.test>';message['Subject']='Invoice: EMAIL-1'
    message.set_content('<script>bad()</script><table><tr><th>Description</th><th>Qty</th><th>Unit cost</th></tr><tr><td>Oat milk</td><td>4</td><td>3.50</td></tr></table>',subtype='html')
    text=extract_document(message.as_bytes(),'invoice.eml')
    assert 'bad()' not in text and 'orders@midwest.test' in text
    data=parse_text(text)
    assert data['lines'][0]['quantity']=='4'


def test_text_pdf_extraction():
    from reportlab.pdfgen.canvas import Canvas
    data=BytesIO();canvas=Canvas(data)
    canvas.drawString(50,750,'Supplier: Example Dairy')
    canvas.drawString(50,725,'Oat milk 12 3.50 42.00')
    canvas.save()
    text=extract_document(data.getvalue(),'receipt.pdf')
    assert 'Example Dairy' in text and parse_text(text)['lines'][0]['quantity']=='12'


@pytest.mark.parametrize('extension',['png','pdf'])
def test_real_photo_and_scanned_pdf_ocr(extension):
    image=Image.new('RGB',(1800,800),'white');draw=ImageDraw.Draw(image)
    for i,text in enumerate(['Supplier: Example Dairy','Invoice: OCR-100','Oat milk 12 3.50 42.00']):
        draw.text((70,80+i*140),text,fill='black',font_size=48)
    data=BytesIO();image.save(data,'PDF' if extension=='pdf' else 'PNG')
    text=extract_document(data.getvalue(),'receipt.'+extension)
    assert 'Oat milk' in text
    assert parse_text(text)['lines'][0]['quantity']=='12'


def test_import_is_read_only_until_confirmed_and_received_once(app,owner):
    draft,created=create_import(owner,TEXT,'receipt.txt')
    assert created and quantity(1,1)==8
    assert draft.data['lines'][0]['product_id']=='1'
    same,created=create_import(owner,TEXT,'same.txt')
    assert not created and same.id==draft.id
    save_review(owner,draft.id,review_form(draft))
    assert quantity(1,1)==8
    token=key();payload={'draft_id':draft.id,'version':draft.version}
    result=execute(owner,'document_receipt',payload,token)
    assert quantity(1,1)==20
    tea=db.session.scalar(select(Product).where(Product.store_id==1,Product.sku=='TEA-NEW'))
    assert quantity(1,tea.id)==6 and tea.category=='Beverages'
    assert execute(owner,'document_receipt',payload,token)['duplicate']
    with pytest.raises(DomainError): execute(owner,'document_receipt',payload,key())
    assert quantity(1,1)==20 and quantity(1,tea.id)==6 and reconciliation(1)==[]


def test_import_atomic_failure_no_new_product_or_partial_stock(app,owner,monkeypatch):
    draft=ready_import(owner)
    import app.services.inventory as inventory
    original=inventory.move
    def fail(actor,op,product,location,delta,reason,kind=None):
        if product.sku=='TEA-NEW': raise RuntimeError('Injected final line failure')
        return original(actor,op,product,location,delta,reason,kind)
    monkeypatch.setattr(inventory,'move',fail)
    with pytest.raises(RuntimeError): execute(owner,'document_receipt',{'draft_id':draft.id,'version':draft.version},key())
    assert quantity(1,1)==8 and db.session.scalar(select(Product.id).where(Product.sku=='TEA-NEW')) is None
    assert db.session.get(DocumentImport,draft.id).status=='reviewed'
    assert reconciliation(1)==[]


def test_document_order_does_not_add_stock_and_owner_can_explain_override(app,owner):
    draft=ready_import(owner)
    oid=create_document_order(owner,draft.id,draft.version)
    assert create_document_order(owner,draft.id,draft.version)==oid
    order=db.session.get(PurchaseOrder,oid)
    assert order.status=='draft' and len(order.items)==2 and quantity(1,1)==8
    with pytest.raises(DomainError): change_order(owner,oid,'approve')
    change_order(owner,oid,'approve',override_reason='Reviewed supplier order for next month')
    assert db.session.get(PurchaseOrder,oid).approval_note=='Reviewed supplier order for next month'
    assert quantity(1,1)==8
    execute(owner,'order_receipt',{'order_id':oid},key())
    assert quantity(1,1)==20 and reconciliation(1)==[]


def test_foreign_product_location_and_stale_review_rejected(app,owner):
    draft,_=create_import(owner,TEXT,'receipt.txt')
    form=review_form(draft);form['line_0_product_id']='2'
    with pytest.raises(DomainError): save_review(owner,draft.id,form)
    form=review_form(draft);form['line_0_location_id']='3'
    with pytest.raises(DomainError): save_review(owner,draft.id,form)
    form=review_form(draft);save_review(owner,draft.id,form)
    with pytest.raises(DomainError,match='another tab'): save_review(owner,draft.id,form)
    assert quantity(1,1)==8


def test_reference_duplicate_blocks_different_document_source(app,owner):
    draft=ready_import(owner);execute(owner,'document_receipt',{'draft_id':draft.id,'version':draft.version},key())
    # Change source text while keeping supplier and invoice reference.
    second=ready_import(owner,TEXT.replace('Green tea','Green tea extra').replace('TEA-NEW','TEA-SECOND'))
    with pytest.raises(DomainError,match='already finalized'):
        execute(owner,'document_receipt',{'draft_id':second.id,'version':second.version},key())
    assert quantity(1,1)==20


def test_multi_product_location_stocktake_review_and_idempotency(app,owner):
    extra=Product(store_id=1,supplier_id=1,sku='COUNT-EXTRA',name='Extra counted product')
    db.session.add(extra);db.session.commit()
    session=create_session(owner,'Annual review','Physical annual review',[1,extra.id],[1,2],2,True)
    assert len(session.lines)==4 and quantity(1,1)==8
    staff=db.session.get(User,2)
    form=counted_form(session)
    record_counts(staff,session.id,form,submit=True)
    assert quantity(1,1)==8 and session.status=='submitted'
    payload={'session_id':session.id,'revision':str(len(session.events))};token=key()
    execute(owner,'count_session',payload,token)
    assert quantity(1,1,1)==2 and quantity(1,1,2)==2 and quantity(1,extra.id)==4
    assert execute(owner,'count_session',payload,token)['duplicate']
    assert reconciliation(1)==[]


def test_stale_sheet_recount_retains_observations(app,owner):
    session=create_session(owner,'Cycle count','Check shelves',[1],[1,2],2)
    record_counts(db.session.get(User,2),session.id,counted_form(session),True)
    execute(owner,'sale',dict(product_id=1,location_id=1,quantity=1),key())
    with pytest.raises(DomainError,match='recount'):
        execute(owner,'count_session',{'session_id':session.id,'revision':str(len(session.events))},key())
    assert (quantity(1,1,1),quantity(1,1,2))==(2,5)
    review_action(owner,session.id,'recount','Sale happened during count',str(len(session.events)))
    assert session.status=='counting' and all(l.counted_quantity is None for l in session.lines)
    assert any(e['action']=='Previous observations' for e in session.events)
    record_counts(db.session.get(User,2),session.id,counted_form(session,'3'),True)
    execute(owner,'count_session',{'session_id':session.id,'revision':str(len(session.events))},key())
    assert quantity(1,1)==6 and reconciliation(1)==[]


def test_stocktake_requires_complete_counts_and_current_revision(app,owner):
    session=create_session(owner,'Annual','Review',[1],[1,2])
    with pytest.raises(DomainError): record_counts(owner,session.id,MultiDict({'revision':str(len(session.events))}),True)
    form=counted_form(session)
    record_counts(owner,session.id,form,False)
    with pytest.raises(DomainError,match='another tab'): record_counts(owner,session.id,form,False)
    assert quantity(1,1)==8


def test_import_and_count_roles_and_blind_expected_data(client,owner):
    session=create_session(owner,'Blind sheet','Independent count',[1],[1,2],2,True)
    client.post('/login',data={'email':'staff@test.test','password':'test-password'})
    assert client.get('/imports').status_code==403
    assert client.post('/stocktakes/new',data={}).status_code==403
    response=client.get(f'/stocktakes/{session.id}')
    assert response.status_code==200 and b'Expected baseline' not in response.data
    assert b'Expected baseline' not in client.get(f'/stocktakes/{session.id}/export.csv').data
    assert client.post(f'/stocktakes/{session.id}',data={'action':'approve'}).status_code==403
    client.post('/logout');client.post('/login',data={'email':'other@test.test','password':'test-password'})
    assert client.get(f'/stocktakes/{session.id}').status_code==404


def test_new_business_pages_render(signed_in,owner):
    draft,_=create_import(owner,TEXT,'receipt.txt')
    for path in ['/imports',f'/imports/{draft.id}','/stocktakes','/counts','/counts?individual=1','/products?view=cards','/products?view=table','/products?category=General&status=low']:
        response=signed_in.get(path)
        assert response.status_code==200,path
    save_review(owner,draft.id,review_form(draft))
    assert signed_in.get(f'/imports/{draft.id}/confirm').status_code==200


def test_counting_window_refreshes_old_request_without_changing_stock(app,owner):
    from app.services.stocktakes import start_counting
    sheet=create_session(owner,'Planned review','Count tomorrow',[1],[1],2)
    execute(owner,'sale',dict(product_id=1,location_id=1,quantity=1),key())
    start_counting(db.session.get(User,2),sheet.id,str(len(sheet.events)))
    assert sheet.lines[0].expected_quantity==2 and quantity(1,1,1)==2
    record_counts(db.session.get(User,2),sheet.id,counted_form(sheet,'2'),True)
    execute(owner,'count_session',{'session_id':sheet.id,'revision':str(len(sheet.events))},key())
    assert quantity(1,1)==7 and reconciliation(1)==[]


def test_supplier_details_can_be_explicitly_updated(app,owner):
    draft,_=create_import(owner,TEXT,'supplier update.txt')
    form=review_form(draft);form['update_supplier']='yes'
    save_review(owner,draft.id,form)
    execute(owner,'document_receipt',{'draft_id':draft.id,'version':draft.version},key())
    supplier=db.session.get(Supplier,1)
    assert supplier.email=='orders@supplier.test' and supplier.phone=='312-555-1234'
    assert supplier.address=='12 Main Street, Chicago IL'


def test_archived_product_restores_with_working_actions_and_stable_qr(signed_in):
    p=Product(store_id=1,supplier_id=1,sku='RESTORE',name='Restorable product',archived=True)
    db.session.add(p);db.session.commit();token=p.qr_token
    html=signed_in.get(f'/products/{p.id}').data
    assert b'Restore product' in html and b'Edit details' not in html
    assert signed_in.post(f'/products/{p.id}/restore').status_code==302
    db.session.refresh(p)
    assert not p.archived and p.qr_token==token
    assert signed_in.get(f'/products/{p.id}/edit').status_code==200


def test_active_count_sheet_blocks_archival(signed_in,owner):
    p=Product(store_id=1,supplier_id=1,sku='REVIEW',name='Pending review product')
    db.session.add(p);db.session.commit()
    sheet=create_session(owner,'Count this item','Physical review',[p.id],[1])
    response=signed_in.post(f'/products/{p.id}/archive',follow_redirects=True)
    assert b'Resolve active stock review sheets' in response.data
    assert not db.session.get(Product,p.id).archived
    response=signed_in.post(f'/stocktakes/{sheet.id}',data={'action':'cancel','review_reason':'Requested the wrong product','revision':str(len(sheet.events))},follow_redirects=True)
    assert b'Cancelled' in response.data and quantity(1,p.id)==0
    signed_in.post(f'/products/{p.id}/archive')
    assert db.session.get(Product,p.id).archived


def test_restore_is_owner_and_store_scoped(client):
    client.post('/login',data={'email':'staff@test.test','password':'test-password'})
    assert client.post('/products/1/restore').status_code==403
    client.post('/logout');client.post('/login',data={'email':'owner@test.test','password':'test-password'})
    assert client.post('/products/2/restore').status_code==404
