from io import BytesIO
from pathlib import Path
from uuid import uuid4
import shutil
from flask import Blueprint,render_template,request,redirect,url_for,flash,send_from_directory,current_app,abort
from flask_login import current_user
from PIL import Image,ImageOps
from werkzeug.utils import secure_filename
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError,OperationalError
from .extensions import db
from .models import DocumentImport,Product,Supplier,Location,PurchaseOrder
from .routes import owner_required,rows,find,fail
from .services.common import DomainError,whole
from .services.document_reader import extract_document,MAX_BYTES
from .services.documents import create_import,save_review,create_document_order
from .services.inventory import execute,quantity

imports=Blueprint('imports',__name__)


@imports.route('/imports',methods=['GET','POST'])
@owner_required
def index():
    if request.method=='POST':
        key=None
        try:
            upload=request.files.get('document')
            if upload and upload.filename:
                content=upload.read(MAX_BYTES+1)
                text=extract_document(content,upload.filename)
                name=Path(upload.filename).name
                key=uuid4().hex+'.bin'
                directory=Path(current_app.config['UPLOAD_DIR'])/'documents';directory.mkdir(exist_ok=True)
                try:
                    with Image.open(BytesIO(content)) as image:
                        if image.format in ('JPEG','PNG','WEBP'):
                            key=uuid4().hex+'.jpg'
                            image=ImageOps.exif_transpose(image).convert('RGB');image.thumbnail((1600,2000))
                            image.save(directory/key,'JPEG',quality=90)
                        else: (directory/key).write_bytes(content)
                except OSError: (directory/key).write_bytes(content)
            else:
                text=request.form.get('source_text','')
                name='Pasted email / document'
            draft,created=create_import(current_user,text,name,key)
            if not created and key:
                (Path(current_app.config['UPLOAD_DIR'])/'documents'/key).unlink(missing_ok=True)
            flash('Document read. Check the suggested details below.' if created else 'This document already exists. Opened its saved review; no stock was added.','success')
            return redirect(url_for('imports.review',ident=draft.id))
        except (DomainError,IntegrityError,OperationalError) as exc:
            fail(exc)
            if key: (Path(current_app.config['UPLOAD_DIR'])/'documents'/key).unlink(missing_ok=True)
    return render_template('imports.html',imports=list(reversed(rows(DocumentImport,False))),ocr_available=bool(shutil.which('tesseract')))


@imports.route('/imports/<int:ident>',methods=['GET','POST'])
@owner_required
def review(ident):
    draft=find(DocumentImport,ident)
    form_data=None
    if request.method=='POST':
        try:
            draft=save_review(current_user,ident,request.form)
            return redirect(url_for('imports.confirm',ident=ident))
        except (DomainError,IntegrityError,OperationalError) as exc:
            fail(exc)
            # Keep invalid input so correcting one row never erases the rest of the list.
            form_data=request.form
    data=draft.data
    if form_data:
        data={**data,'metadata':{k:form_data.get(k,'') for k in data['metadata']},'supplier_id':form_data.get('supplier_id',''),'update_supplier':form_data.get('update_supplier')=='yes',
            'lines':[{k:form_data.get(f'line_{key}_{k}','') for k in ('product_id','name','sku','quantity','cost','price','category','unit','location_id','description','reorder_level')} for key in form_data.getlist('line_key')[:100]]}
    open_orders=[]
    supplier_id=str(data.get('supplier_id',''))
    if supplier_id.isdigit():
        open_orders=db.session.scalars(select(PurchaseOrder).where(PurchaseOrder.store_id==current_user.store_id,
            PurchaseOrder.supplier_id==int(supplier_id),PurchaseOrder.status.in_(['draft','approved'])).order_by(PurchaseOrder.id.desc()).limit(10)).all()
    return render_template('import_review.html',draft=draft,data=data,products=rows(Product),suppliers=rows(Supplier),locations=rows(Location),open_orders=open_orders,editable=draft.status in ('draft','reviewed'))


@imports.route('/imports/<int:ident>/confirm',methods=['GET','POST'])
@owner_required
def confirm(ident):
    draft=find(DocumentImport,ident)
    if request.method=='POST':
        try:
            if request.form.get('confirmed')!='yes': raise DomainError('Confirm that the document and physical delivery/order were reviewed.')
            if request.form.get('action')=='order':
                order_id=create_document_order(current_user,ident,request.form.get('version'))
                flash('Supplier order saved as a draft. Stock is unchanged.','success')
                return redirect(url_for('orders.order_detail',ident=order_id))
            if request.form.get('action')!='receive': raise DomainError('Choose an order draft or delivered stock.')
            result=execute(current_user,'document_receipt',{'draft_id':ident,'version':whole(request.form.get('version'))},request.form.get('token'))
            flash('Already received; no duplicate stock added.' if result['duplicate'] else 'All reviewed delivery lines were received together.','success')
            return redirect(url_for('imports.review',ident=ident))
        except (DomainError,IntegrityError,OperationalError) as exc: fail(exc)
    if draft.status not in ('reviewed','received','ordered'):
        return redirect(url_for('imports.review',ident=ident))
    balances={}
    cumulative={}
    for i,line in enumerate(draft.data['lines']):
        pid=int(line['product_id']) if line.get('product_id') else None
        pair=(pid or line['sku'],int(line['location_id']))
        before=cumulative.get(pair,quantity(current_user.store_id,pid,pair[1]) if pid else 0)
        balances[i]=(before,before+int(line['quantity']))
        cumulative[pair]=before+int(line['quantity'])
    return render_template('import_confirm.html',draft=draft,data=draft.data,locations={l.id:l for l in rows(Location,False)},balances=balances,token=request.form.get('token') or uuid4().hex)


@imports.get('/imports/<int:ident>/source')
@owner_required
def source(ident):
    draft=find(DocumentImport,ident)
    if not draft.source_key: abort(404)
    image=draft.source_key.endswith('.jpg')
    return send_from_directory(Path(current_app.config['UPLOAD_DIR'])/'documents',draft.source_key,
        as_attachment=not image,mimetype='image/jpeg' if image else 'application/octet-stream',download_name=secure_filename(draft.source_name) or 'source-document.bin')
