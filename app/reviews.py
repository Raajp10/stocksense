from uuid import uuid4
from flask import Blueprint,render_template,request,redirect,url_for,flash,abort
from flask_login import login_required,current_user
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError,OperationalError
from .extensions import db
from .models import CountSession,CountSessionLine,Product,Location,User
from .routes import owner_required,rows,find,fail,csv_response
from .services.common import DomainError
from .services.inventory import execute,balance,quantity
from .services.stocktakes import create_session,record_counts,review_action,accessible,start_counting

reviews=Blueprint('reviews',__name__)


@reviews.get('/stocktakes')
@login_required
def list_reviews():
    query=select(CountSession).where(CountSession.store_id==current_user.store_id)
    if current_user.role!='owner': query=query.where((CountSession.assignee_id==None)|(CountSession.assignee_id==current_user.id))
    sessions=db.session.scalars(query.order_by(CountSession.id.desc())).all()
    return render_template('stocktakes.html',sessions=sessions,users={u.id:u for u in rows(User,False)},products=rows(Product),locations=rows(Location),
        categories=sorted({p.category for p in rows(Product)}),product_totals={p.id:quantity(current_user.store_id,p.id) for p in rows(Product)})


@reviews.post('/stocktakes/new')
@owner_required
def new_review():
    try:
        session=create_session(current_user,request.form.get('title',''),request.form.get('reason',''),
            request.form.getlist('product_ids'),request.form.getlist('location_ids'),request.form.get('assignee_id'),
            request.form.get('show_expected')!='yes',request.form.get('due_date'))
        flash('Count sheet requested. Inventory stays unchanged until owner approval.','success')
        return redirect(url_for('reviews.detail',ident=session.id))
    except (DomainError,IntegrityError,OperationalError) as exc: fail(exc)
    return list_reviews()


@reviews.route('/stocktakes/<int:ident>',methods=['GET','POST'])
@login_required
def detail(ident):
    session=find(CountSession,ident)
    try: accessible(session,current_user)
    except DomainError: abort(404)
    if request.method=='POST':
        try:
            action=request.form.get('action')
            if action=='start':
                start_counting(current_user,ident,request.form.get('revision'))
            elif action in ('save','submit'):
                record_counts(current_user,ident,request.form,submit=action=='submit')
            elif action in ('recount','reject','cancel'):
                if current_user.role!='owner': abort(403)
                review_action(current_user,ident,action,request.form.get('review_reason',''),request.form.get('revision'))
            elif action=='approve':
                if current_user.role!='owner': abort(403)
                if request.form.get('confirmed')!='yes': raise DomainError('Check the variance review confirmation before approving.')
                execute(current_user,'count_session',{'session_id':ident,'revision':request.form.get('revision')},request.form.get('token'))
            else: raise DomainError('Choose a count/review action.')
            flash('Count sheet updated.','success')
            return redirect(url_for('reviews.detail',ident=ident))
        except (DomainError,IntegrityError,OperationalError) as exc: fail(exc)
    products={p.id:p for p in rows(Product,False)};locations={l.id:l for l in rows(Location,False)}
    show_expected=current_user.role=='owner' or not session.blind
    state={}
    for line in session.lines:
        row=balance(current_user.store_id,line.product_id,line.location_id)
        current=row.quantity if row else 0
        state[line.id]={'current':current,'stale':(row.version if row else 0)!=line.observed_version,
            'variance':None if line.counted_quantity is None else line.counted_quantity-line.expected_quantity}
    stale=any(v['stale'] for v in state.values())
    return render_template('stocktake_detail.html',sheet=session,products=products,locations=locations,state=state,
        stale=stale,untouched=all(line.counted_quantity is None for line in session.lines),show_expected=show_expected,users={u.id:u for u in rows(User,False)},token=request.form.get('token') or uuid4().hex)


@reviews.get('/stocktakes/<int:ident>/export.csv')
@login_required
def export(ident):
    session=find(CountSession,ident)
    try: accessible(session,current_user)
    except DomainError: abort(404)
    owner=current_user.role=='owner' or not session.blind
    columns=['Review','Product','SKU','Category','Unit','Location','Counted','Note']
    if owner: columns+=['Expected at request','Variance']
    data=[]
    for line in session.lines:
        p=find(Product,line.product_id);l=find(Location,line.location_id)
        row=[session.title,p.name,p.sku,p.category,p.unit,l.code,'' if line.counted_quantity is None else line.counted_quantity,line.note]
        if owner: row+=[line.expected_quantity,'' if line.counted_quantity is None else line.counted_quantity-line.expected_quantity]
        data.append(row)
    return csv_response(f'stock-review-{ident}',columns,data)
