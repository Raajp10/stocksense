from datetime import date
from sqlalchemy import select
from ..extensions import db
from ..models import CountSession,CountSessionLine,User,Product,Location,now
from .common import DomainError,lock_store,scoped,whole
from .inventory import balance,quantity


def event(session,actor,action,detail=''):
    session.events=list(session.events or [])+[dict(actor=actor.name,action=action,detail=detail,at=now().isoformat(timespec='seconds'))]


def accessible(session,actor):
    if session.store_id!=actor.store_id or (actor.role!='owner' and session.assignee_id not in (None,actor.id)):
        raise DomainError('Stock review not found or not assigned to you.')


def create_session(actor,title,reason,product_ids,location_ids,assignee_id=None,blind=True,due_date=None):
    try:
        actor=lock_store(actor,True)
        title=title.strip();reason=reason.strip()
        if not title or len(title)>120 or not reason or len(reason)>250:
            raise DomainError('Enter a title (up to 120 characters) and purpose (up to 250).')
        products=sorted(set(whole(i,1) for i in product_ids));locations=sorted(set(whole(i,1) for i in location_ids))
        if not products or not locations or len(products)*len(locations)>500:
            raise DomainError('Select products and locations, up to 500 product/location pairs per review.')
        for pid in products: scoped(Product,pid,actor.store_id,True)
        for lid in locations: scoped(Location,lid,actor.store_id,True)
        if assignee_id:
            user=scoped(User,whole(assignee_id,1),actor.store_id)
            if not user.active: raise DomainError('Choose an active team member.')
            assignee_id=user.id
        else: assignee_id=None
        try: due=date.fromisoformat(due_date) if due_date else None
        except ValueError: raise DomainError('Enter a valid due date.')
        session=CountSession(store_id=actor.store_id,title=title,reason=reason,created_by=actor.id,
            assignee_id=assignee_id,blind=blind,due_date=due)
        db.session.add(session);db.session.flush()
        for pid in products:
            for lid in locations:
                row=balance(actor.store_id,pid,lid)
                db.session.add(CountSessionLine(store_id=actor.store_id,session_id=session.id,product_id=pid,
                    location_id=lid,expected_quantity=row.quantity if row else 0,observed_version=row.version if row else 0))
        event(session,actor,'Requested',f'{len(products)} products at {len(locations)} locations')
        db.session.commit();return session
    except Exception:
        db.session.rollback();raise


def record_counts(actor,ident,form,submit=False):
    try:
        actor=lock_store(actor)
        session=scoped(CountSession,ident,actor.store_id);accessible(session,actor)
        if session.status!='counting': raise DomainError('This sheet is no longer open for counting.')
        if whole(form.get('revision'))!=len(session.events or []):
            raise DomainError('This count sheet changed in another tab. Reload before entering more counts.')
        if session.assignee_id is None and actor.role!='owner':
            session.assignee_id=actor.id
        values=[]
        for line in session.lines:
            value=form.get(f'count_{line.id}','').strip()
            counted=whole(value) if value else None
            note=form.get(f'note_{line.id}','').strip()
            if len(note)>250: raise DomainError('Keep each note within 250 characters.')
            if submit and counted is None:
                raise DomainError('Count every row before submitting. Use zero only when you physically found none.')
            values.append((line,counted,note))
        for line,counted,note in values:
            line.counted_quantity=counted;line.note=note
        if submit:
            session.status='submitted';session.submitted_at=now()
        event(session,actor,'Submitted for review' if submit else 'Progress saved')
        db.session.commit();return session
    except Exception:
        db.session.rollback();raise


def review_action(actor,ident,action,reason='',revision=None):
    try:
        actor=lock_store(actor,True)
        session=scoped(CountSession,ident,actor.store_id)
        if action=='cancel':
            if session.status!='counting': raise DomainError('Only an open counting request can be cancelled.')
        elif session.status!='submitted': raise DomainError('Only submitted sheets can be reviewed.')
        if whole(revision)!=len(session.events or []): raise DomainError('The review changed. Reload before reviewing it.')
        reason=reason.strip()
        if not reason or len(reason)>250: raise DomainError('Enter a review/recount reason of 1–250 characters.')
        if action=='recount':
            observations=[{'product_id':l.product_id,'location_id':l.location_id,'count':l.counted_quantity,'expected':l.expected_quantity} for l in session.lines]
            for line in session.lines:
                row=balance(actor.store_id,line.product_id,line.location_id)
                line.expected_quantity=row.quantity if row else 0
                line.observed_version=row.version if row else 0
                line.counted_quantity=None;line.note=''
            session.status='counting';session.submitted_at=None
            event(session,actor,'Recount requested',reason)
            session.events=list(session.events)+[dict(action='Previous observations',observations=observations,actor=actor.name,at=now().isoformat(timespec='seconds'))]
        elif action in ('reject','cancel'):
            session.status='rejected';session.reviewed_by=actor.id;session.reviewed_at=now()
            event(session,actor,'Cancelled before submission' if action=='cancel' else 'Rejected',reason)
        else: raise DomainError('Unknown review action.')
        db.session.commit();return session
    except Exception:
        db.session.rollback();raise


def approve_session(actor,op,payload):
    from .inventory import move
    session=scoped(CountSession,whole(payload['session_id'],1),actor.store_id)
    if session.status!='submitted': raise DomainError('Only a submitted review can be approved.')
    if whole(payload.get('revision'))!=len(session.events or []): raise DomainError('The count sheet changed. Reload before approving.')
    # Validate every row before any movement is written. One stale row prevents all changes.
    for line in session.lines:
        row=balance(actor.store_id,line.product_id,line.location_id)
        if (row.version if row else 0)!=line.observed_version:
            raise DomainError('Stock changed after this sheet was requested. Request a recount before approving.')
        if line.counted_quantity is None: raise DomainError('Every row needs a physical count.')
        scoped(Product,line.product_id,actor.store_id,True)
        scoped(Location,line.location_id,actor.store_id,True)
    for line in sorted(session.lines,key=lambda l:(l.product_id,l.location_id)):
        product=scoped(Product,line.product_id,actor.store_id,True)
        delta=line.counted_quantity-quantity(actor.store_id,line.product_id,line.location_id)
        move(actor,op,product,line.location_id,delta,f'Stock review #{session.id}: {line.note or session.reason}','count_session')
    session.status='approved';session.reviewed_by=actor.id;session.reviewed_at=now()
    event(session,actor,'Approved',f'{len(session.lines)} location counts reconciled atomically')
    return {'session_id':session.id,'lines':len(session.lines)}


def start_counting(actor,ident,revision):
    """Refresh an untouched sheet when the team actually starts its physical count."""
    try:
        actor=lock_store(actor)
        session=scoped(CountSession,ident,actor.store_id);accessible(session,actor)
        if session.status!='counting' or any(line.counted_quantity is not None for line in session.lines):
            raise DomainError('Only an untouched count sheet can start a new counting window. Ask the owner for a recount after submitting observations.')
        if whole(revision)!=len(session.events or []): raise DomainError('The sheet changed. Reload before starting.')
        if session.assignee_id is None and actor.role!='owner': session.assignee_id=actor.id
        for line in session.lines:
            row=balance(actor.store_id,line.product_id,line.location_id)
            line.expected_quantity=row.quantity if row else 0
            line.observed_version=row.version if row else 0
        event(session,actor,'Counting window started','Expected baseline refreshed before physical counting; no stock changed')
        db.session.commit();return session
    except Exception:
        db.session.rollback();raise
