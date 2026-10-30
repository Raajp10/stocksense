from io import BytesIO
from pathlib import Path
from uuid import uuid4
from importlib.util import find_spec
from flask import Blueprint,render_template,request,redirect,url_for,flash,send_from_directory,current_app,abort
from flask_login import current_user,login_required
from PIL import Image,ImageOps
from werkzeug.utils import secure_filename
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError,OperationalError
from .extensions import db
from .models import DocumentImport,Product,Supplier,Location,PurchaseOrder
from .routes import owner_required,rows,find,fail
from .services.common import DomainError,whole
from .services.document_reader import extract_document,MAX_BYTES
from .services.documents import create_import,save_review,create_document_order,receipt_movements
from .services.inventory import execute,quantity
from .services.document_checks import inspect_document

imports=Blueprint('imports',__name__)


def find_import(ident):
    draft=find(DocumentImport,ident)
    if current_user.role!='owner' and draft.created_by!=current_user.id: abort(404)
    return draft


@imports.route('/imports',methods=['GET','POST'])
@login_required
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
            return redirect(url_for('imports.review',ident=draft.id,**({'advanced':'1'} if current_user.role=='owner' and request.args.get('advanced')=='1' else {})))
        except (DomainError,IntegrityError,OperationalError) as exc:
            fail(exc)
            if key: (Path(current_app.config['UPLOAD_DIR'])/'documents'/key).unlink(missing_ok=True)
    return render_template('imports.html',imports=[d for d in reversed(rows(DocumentImport,False)) if current_user.role=='owner' or d.created_by==current_user.id],ocr_available=find_spec('rapidocr_onnxruntime') is not None)


@imports.route('/imports/<int:ident>',methods=['GET','POST'])
@login_required
def review(ident):
    draft=find_import(ident)
    form_data=None
    if request.method=='POST':
        try:
            if request.form.get('mode')=='quick':
                if draft.status=='received':
                    flash('This bill has already been added. No duplicate stock was added.','success')
                    return redirect(url_for('imports.review',ident=ident))
                if request.form.get('confirmed')!='yes': raise DomainError('Confirm that you checked the items and received the delivery.')
                from .services.quick_receive import review_form
                draft=save_review(current_user,ident,review_form(current_user,draft,request.form))
                result=execute(current_user,'document_receipt',{'draft_id':ident,'version':draft.version},request.form.get('token'))
                flash('Items added to stock. New products without a selling price can be priced by the owner later.','success')
                return redirect(url_for('imports.review',ident=ident))
            if current_user.role!='owner': abort(403)
            draft=save_review(current_user,ident,request.form)
            return redirect(url_for('imports.confirm',ident=ident))
        except (DomainError,IntegrityError,OperationalError) as exc:
            fail(exc)
            # Keep invalid input so correcting one row never erases the rest of the list.
            form_data=request.form
    data={**draft.data,'validation':inspect_document(draft.data['metadata'],draft.data['lines'])}
    if form_data:
        data={**data,'metadata':data['metadata'] if form_data.get('mode')=='quick' else {k:form_data.get(k,'') for k in data['metadata']},'supplier_id':form_data.get('supplier_id',''),'update_supplier':form_data.get('update_supplier')=='yes',
            'lines':[{**{k:form_data.get(f'line_{key}_{k}','') for k in ('product_id','name','sku','quantity','cost','price','category','unit','location_id','description','reorder_level','source_total')},'_form_key':key} for key in form_data.getlist('line_key')[:100]]}
    open_orders=[]
    supplier_id=str(data.get('supplier_id',''))
    if supplier_id.isdigit():
        open_orders=db.session.scalars(select(PurchaseOrder).where(PurchaseOrder.store_id==current_user.store_id,
            PurchaseOrder.supplier_id==int(supplier_id),PurchaseOrder.status.in_(['draft','approved'])).order_by(PurchaseOrder.id.desc()).limit(10)).all()
    from .services.quick_receive import default_location
    advanced=current_user.role=='owner' and request.args.get('advanced')=='1'
    return render_template('import_review.html' if advanced else 'import_quick.html',advanced=advanced,destination=request.form.get('destination') or str(default_location(current_user.store_id)),token=request.form.get('token') or uuid4().hex,draft=draft,data=data,products=rows(Product),suppliers=rows(Supplier),locations=rows(Location),open_orders=open_orders,editable=draft.status in ('draft','reviewed'))


@imports.route('/imports/<int:ident>/confirm',methods=['GET','POST'])
@owner_required
def confirm(ident):
    draft=find_import(ident)
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
            return redirect(url_for('imports.review',ident=ident,advanced=1))
        except (DomainError,IntegrityError,OperationalError) as exc: fail(exc)
    if draft.status not in ('reviewed','received','ordered'):
        return redirect(url_for('imports.review',ident=ident,advanced=1))
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
@login_required
def source(ident):
    draft=find_import(ident)
    if not draft.source_key: abort(404)
    image=draft.source_key.endswith('.jpg')
    return send_from_directory(Path(current_app.config['UPLOAD_DIR'])/'documents',draft.source_key,
        as_attachment=not image,mimetype='image/jpeg' if image else 'application/octet-stream',download_name=secure_filename(draft.source_name) or 'source-document.bin')


@imports.post('/imports/<int:ident>/reread')
@owner_required
def reread(ident):
    previous=find(DocumentImport,ident)
    try:
        if not previous.source_key: raise DomainError('No saved source file is available. Upload the original image/PDF to read it again.')
        content=(Path(current_app.config['UPLOAD_DIR'])/'documents'/previous.source_key).read_bytes()
        text=extract_document(content,previous.source_name)
        draft,created=create_import(current_user,text,previous.source_name,previous.source_key)
        if created:
            from .services.common import lock_store
            lock_store(current_user,True)
            draft.data={**draft.data,'reprocessed_from':previous.id}
            db.session.commit()
        flash('Source read again with the new local ML/layout pipeline. Review this draft; existing inventory was not changed.','success')
        return redirect(url_for('imports.review',ident=draft.id))
    except (DomainError,IntegrityError,OperationalError,OSError) as exc:
        fail(exc)
        return redirect(url_for('imports.review',ident=ident))


@imports.route('/imports/<int:ident>/reverse',methods=['GET','POST'])
@owner_required
def reverse(ident):
    draft=find_import(ident)
    if request.method=='POST':
        try:
            if request.form.get('confirmed')!='yes': raise DomainError('Confirm the exact original quantities before reversing this receipt.')
            execute(current_user,'document_reversal',{'draft_id':ident,'reason':request.form.get('reason','').strip()},request.form.get('token'))
            flash('The original receipt was reversed with compensating movements. Its history is preserved.','success')
            return redirect(url_for('imports.review',ident=ident))
        except (DomainError,IntegrityError,OperationalError) as exc: fail(exc)
    if draft.status!='received' or draft.data.get('reversal'):
        return redirect(url_for('imports.review',ident=ident))
    movements=receipt_movements(current_user,draft)
    projections=[]
    for movement in movements:
        product=find(Product,movement.product_id);location=find(Location,movement.location_id)
        current=quantity(current_user.store_id,product.id,location.id)
        projections.append({'product':product,'location':location,'received':movement.delta,'before':current,'after':current-movement.delta})
    return render_template('import_reverse.html',draft=draft,projections=projections,
        sufficient=all(row['after']>=0 for row in projections),token=request.form.get('token') or uuid4().hex)
