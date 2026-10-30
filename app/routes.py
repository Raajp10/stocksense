"""HTTP adapters: authorize, validate forms, call domain services, render results."""
from functools import wraps
from decimal import Decimal, InvalidOperation
from io import BytesIO, StringIO
from pathlib import Path
import csv
from uuid import uuid4
from flask import (Blueprint, render_template, request, redirect, url_for, flash, abort,
                   send_file, send_from_directory, current_app, jsonify)
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from sqlalchemy import select, or_, func
from sqlalchemy.exc import IntegrityError, OperationalError
import qrcode
from .extensions import db
from .models import (User, Store, Product, Supplier, Location, StockBalance, StockMovement,
    ShelfRule, PurchaseOrder, PurchaseOrderItem, StockCountRequest, Sale, DocumentImport, CountSession, CountSessionLine)
from .services.common import DomainError, scoped, lock_store, whole
from .services.inventory import execute, quantity, submit_count
from .services.reorder import recommendations, shelf_refills
from .services.orders import create_drafts, change_order
from .services.scan import resolve
from .services.media import save_image, remove_image
from .services.reporting import report

auth = Blueprint("auth", __name__)
catalog = Blueprint("catalog", __name__)
inventory = Blueprint("inventory", __name__)
orders = Blueprint("orders", __name__)
dashboard = Blueprint("dashboard", __name__)
exports = Blueprint("exports", __name__)


def owner_required(fn):
    @wraps(fn)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.role != "owner":
            abort(403)
        return fn(*args, **kwargs)
    return wrapped


def sid():
    return current_user.store_id


def find(model, ident, active=False):
    try:
        return scoped(model, ident, sid(), active)
    except DomainError:
        abort(404)


def rows(model, active=True):
    query = select(model).where(model.store_id == sid())
    if active and hasattr(model, "archived"):
        query = query.where(model.archived.is_(False))
    return db.session.scalars(query.order_by(model.id)).all()


def text_field(name, maxlen=100, required=True):
    value = request.form.get(name, "").strip()
    if (required and not value) or len(value) > maxlen:
        raise DomainError(f"{name.replace('_', ' ').title()} must be {'1' if required else '0'}–{maxlen} characters.")
    return value


def cents(name):
    try:
        value = Decimal(request.form.get(name, ""))
        if not value.is_finite() or value < 0 or value > Decimal("10000000") or value != value.quantize(Decimal("0.01")):
            raise InvalidOperation
        return int(value*100)
    except (InvalidOperation, ValueError):
        raise DomainError("Enter a nonnegative price with at most two decimal places.")


def fail(exc):
    db.session.rollback()
    if isinstance(exc, IntegrityError):
        flash("That SKU, code, email or record already exists, or a related record is invalid.", "danger")
    elif isinstance(exc, OperationalError):
        flash("The database is busy. Retry the same confirmation safely.", "danger")
    else:
        flash(str(exc), "danger")


@auth.route("/login", methods=["GET", "POST"])
def login_view():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = db.session.scalar(select(User).where(User.email == email))
        # Always perform a password hash check, including for unknown users.
        dummy = current_app.config.setdefault("DUMMY_PASSWORD_HASH", generate_password_hash("unusable-login-password"))
        valid = check_password_hash(user.password_hash if user else dummy, request.form.get("password", ""))
        if user and user.active and valid:
            login_user(user)
            return redirect(url_for("dashboard.index"))
        flash("Email or password is incorrect.", "danger")
    return render_template("login.html")


@auth.post("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login_view"))


@dashboard.get("/")
@login_required
def index():
    try:
        data = report(sid(), request.args.get("start"), request.args.get("end"))
    except DomainError as exc:
        fail(exc)
        return redirect(url_for("dashboard.index"))
    return render_template("dashboard.html", data=data)


@catalog.get("/products")
@login_required
def products():
    query = select(Product).where(Product.store_id == sid())
    if request.args.get("archived") != "1":
        query = query.where(Product.archived.is_(False))
    term = request.args.get("q", "").strip()[:100]
    if term:
        query = query.where(or_(Product.name.ilike(f"%{term}%"), Product.sku.ilike(f"%{term}%"), Product.category.ilike(f"%{term}%")))
    if request.args.get("location"):
        loc = find(Location, whole(request.args["location"], 1))
        query = query.join(StockBalance, StockBalance.product_id == Product.id).where(
            StockBalance.location_id == loc.id, StockBalance.quantity > 0)
    category=request.args.get('category','').strip()[:60]
    if category:
        query=query.where(Product.category==category)
    items = db.session.scalars(query.order_by(Product.name)).all()
    quantities={p.id:quantity(sid(),p.id) for p in items}
    status=request.args.get('status','')
    if status=='low': items=[p for p in items if quantities[p.id]<=p.reorder_level]
    elif status=='empty': items=[p for p in items if quantities[p.id]==0]
    elif status=='in_stock': items=[p for p in items if quantities[p.id]>p.reorder_level]
    sort=request.args.get('sort','name')
    if sort=='stock': items.sort(key=lambda p:(quantities[p.id],p.name.casefold()))
    elif sort=='recent': items.sort(key=lambda p:p.created_at,reverse=True)
    elif sort=='category': items.sort(key=lambda p:(p.category.casefold(),p.name.casefold()))
    categories=db.session.execute(select(Product.category,func.count(Product.id)).where(
        Product.store_id==sid(),Product.archived.is_(False)).group_by(Product.category).order_by(Product.category)).all()
    return render_template("products.html", products=items, quantities=quantities, locations=rows(Location),
        categories=categories,view='table' if request.args.get('view')=='table' else 'cards',
        low_count=sum(quantities[p.id]<=p.reorder_level for p in items),
        suppliers={s.id:s for s in rows(Supplier,False)})


@catalog.route("/products/new", methods=["GET", "POST"])
@catalog.route("/products/<int:ident>/edit", methods=["GET", "POST"])
@owner_required
def product_edit(ident=None):
    product = find(Product, ident, True) if ident else None
    if request.method == "POST":
        try:
            lock_store(current_user, True)
            supplier_id = whole(request.form.get("supplier_id"), 1)
            scoped(Supplier, supplier_id, sid(), True)
            values = dict(name=text_field("name",120), sku=text_field("sku",60),
                description=text_field("description",1000,False), category=text_field("category",60),
                unit=text_field("unit",30), cost_cents=cents("cost"), price_cents=cents("price"),
                reorder_level=whole(request.form.get("reorder_level")), supplier_id=supplier_id)
            import re
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,60}", values["sku"]):
                raise DomainError("SKU may contain letters, numbers, dots, underscores and hyphens.")
            if not product:
                opening = whole(request.form.get("opening_quantity", "0"))
                location_id = whole(request.form.get("location_id"), 1) if opening else None
                if opening:
                    scoped(Location, location_id, sid(), True)
                product = Product(store_id=sid(), **values)
                db.session.add(product)
                db.session.flush()
                if opening:
                    # Catalog and opening operation share a transaction: execute commits both.
                    execute(current_user, "opening", {"product_id":product.id,"quantity":opening,"location_id":location_id}, request.form.get("token"))
                else:
                    db.session.commit()
            else:
                for key,value in values.items():
                    setattr(product, key, value)
                db.session.commit()
            flash("Product saved. Add or replace its photo below.", "success")
            return redirect(url_for("catalog.product_detail", ident=product.id))
        except (DomainError, IntegrityError, OperationalError) as exc:
            fail(exc)
    return render_template("product_form.html", product=product, suppliers=rows(Supplier), locations=rows(Location), categories=sorted({p.category for p in rows(Product)}), token=request.form.get("token") or uuid4().hex)


@catalog.get("/products/<int:ident>")
@login_required
def product_detail(ident):
    product = find(Product, ident)
    balances = [(l, quantity(sid(), product.id, l.id)) for l in rows(Location,False)]
    history = db.session.execute(select(StockMovement, Location.code, User.name).join(
        Location, Location.id == StockMovement.location_id).join(User, User.id == StockMovement.actor_id).where(
        StockMovement.store_id == sid(), StockMovement.product_id == ident).order_by(StockMovement.id.desc()).limit(100)).all()
    return render_template("product_detail.html", product=product, balances=balances, total=quantity(sid(),ident), history=history)


@catalog.post("/products/<int:ident>/photo")
@owner_required
def product_photo(ident):
    product = find(Product, ident, True)
    key = None
    try:
        upload = request.files.get("photo")
        if not upload or not upload.filename:
            raise DomainError("Choose a product photo.")
        key = save_image(upload)
        lock_store(current_user, True)
        product = find(Product, ident, True)
        old = product.image_key
        product.image_key = key
        db.session.commit()
        remove_image(old)
        flash("Photo saved.", "success")
    except (DomainError, IntegrityError, OperationalError) as exc:
        fail(exc)
        if key:
            remove_image(key)
    return redirect(url_for("catalog.product_detail",ident=ident))


@catalog.get("/products/<int:ident>/photo")
@login_required
def photo(ident):
    product = find(Product, ident)
    if not product.image_key:
        return send_from_directory(current_app.static_folder, "placeholder.svg")
    return send_from_directory(current_app.config["UPLOAD_DIR"], product.image_key, max_age=0)


@catalog.get("/products/<int:ident>/qr.png")
@login_required
def qr(ident):
    p = find(Product,ident)
    buffer = BytesIO()
    qrcode.make(p.qr_payload).save(buffer, format="PNG")
    buffer.seek(0)
    return send_file(buffer,mimetype="image/png")


@catalog.get("/products/<int:ident>/label")
@login_required
def label(ident):
    return render_template("label.html", product=find(Product,ident))


@catalog.post("/<entity>/<int:ident>/archive")
@owner_required
def archive(entity,ident):
    model = {"products":Product,"suppliers":Supplier,"locations":Location}.get(entity)
    if not model:
        abort(404)
    try:
        lock_store(current_user,True)
        obj = find(model,ident,True)
        if model in (Location,Product):
            reference=CountSessionLine.location_id if model==Location else CountSessionLine.product_id
            if db.session.scalar(select(CountSessionLine.id).join(CountSession,CountSession.id==CountSessionLine.session_id).where(
                CountSession.store_id==sid(),CountSession.status.in_(['counting','submitted']),reference==ident).limit(1)):
                raise DomainError('Resolve active stock review sheets before archiving this record.')
        if model == Location:
            in_stock = db.session.scalar(select(func.count()).select_from(StockBalance).where(StockBalance.store_id==sid(),StockBalance.location_id==ident,StockBalance.quantity>0))
            pending = db.session.scalar(select(func.count()).select_from(StockCountRequest).where(StockCountRequest.store_id==sid(),StockCountRequest.location_id==ident,StockCountRequest.status=="pending"))
            open_lines = db.session.scalar(select(func.count()).select_from(PurchaseOrderItem).join(PurchaseOrder,PurchaseOrder.id==PurchaseOrderItem.order_id).where(PurchaseOrder.store_id==sid(),PurchaseOrder.status.in_(["draft","approved"]),PurchaseOrderItem.destination_id==ident))
            rules = db.session.scalar(select(func.count()).select_from(ShelfRule).where(ShelfRule.store_id==sid(),or_(ShelfRule.shelf_id==ident,ShelfRule.source_id==ident)))
            if in_stock or pending or open_lines or rules:
                raise DomainError("Move stock and resolve counts, order lines and shelf rules before archiving this location.")
        elif model == Product:
            if db.session.scalar(select(StockCountRequest.id).where(StockCountRequest.store_id==sid(),StockCountRequest.product_id==ident,StockCountRequest.status=='pending').limit(1)):
                raise DomainError('Resolve pending physical counts before archiving this product.')
            if quantity(sid(),ident):
                raise DomainError("Record an approved stock count to resolve remaining units before archiving.")
            if db.session.scalar(select(PurchaseOrderItem.id).join(PurchaseOrder, PurchaseOrder.id==PurchaseOrderItem.order_id).where(PurchaseOrder.store_id==sid(),PurchaseOrder.status.in_(["draft","approved"]),PurchaseOrderItem.product_id==ident).limit(1)):
                raise DomainError("Resolve open orders before archiving this product.")
        elif db.session.scalar(select(Product.id).where(Product.store_id==sid(),Product.supplier_id==ident,Product.archived.is_(False)).limit(1)):
            raise DomainError("Reassign or archive active products before archiving this supplier.")
        obj.archived=True
        db.session.commit()
        flash("Record archived; history retained.","success")
    except (DomainError,IntegrityError,OperationalError) as exc:
        fail(exc)
    return redirect(url_for("catalog.products") if model==Product else url_for("catalog.manage",entity=entity))


@catalog.post('/<entity>/<int:ident>/restore')
@owner_required
def restore(entity,ident):
    model={'products':Product,'suppliers':Supplier,'locations':Location}.get(entity)
    if not model: abort(404)
    try:
        lock_store(current_user,True)
        obj=find(model,ident)
        if model==Product and obj.supplier.archived:
            raise DomainError('Restore this product’s supplier first, then restore the product.')
        obj.archived=False
        db.session.commit()
        flash('Record restored. Existing stock history and QR labels are retained.','success')
    except (DomainError,IntegrityError,OperationalError) as exc: fail(exc)
    return redirect(url_for('catalog.product_detail',ident=ident) if model==Product else url_for('catalog.manage',entity=entity))


@catalog.route("/manage/<entity>",methods=["GET","POST"])
@catalog.route("/manage/<entity>/<int:ident>",methods=["GET","POST"])
@owner_required
def manage(entity,ident=None):
    model={"suppliers":Supplier,"locations":Location,"staff":User}.get(entity)
    if not model:
        abort(404)
    obj=find(model,ident) if ident else None
    if request.method=="POST":
        try:
            lock_store(current_user,True)
            if entity=="suppliers":
                values=dict(name=text_field("name"),contact=text_field("contact",250,False),email=text_field("email",150,False),phone=text_field("phone",60,False),address=text_field("address",500,False),lead_time_days=whole(request.form.get("lead_time_days"),0,365),safety_days=whole(request.form.get("safety_days"),0,365))
            elif entity=="locations":
                kind=request.form.get("kind")
                if kind not in ("shelf","backroom","general"):
                    raise DomainError("Select a valid location type.")
                values=dict(name=text_field("name"),code=text_field("code",40),kind=kind,
                    **{k:text_field(k,40 if k!="area" else 60,False) for k in ("area","aisle","shelf","bin")})
            else:
                email=text_field("email",150).lower()
                if "@" not in email:
                    raise DomainError("Enter a valid email.")
                values=dict(name=text_field("name"),email=email,role="staff",active=request.form.get("active")=="1")
                if obj and obj.role=="owner":
                    raise DomainError("Owner accounts cannot be edited through staff settings.")
                password=request.form.get("password","")
                if password or not obj:
                    if len(password)<10 or len(password)>128:
                        raise DomainError("Use a password of 10–128 characters.")
                    values["password_hash"]=generate_password_hash(password)
            if obj:
                for k,v in values.items():
                    setattr(obj,k,v)
            else:
                obj=model(store_id=sid(),**values)
                db.session.add(obj)
            db.session.commit()
            flash("Saved successfully.","success")
            return redirect(url_for("catalog.manage",entity=entity))
        except (DomainError,IntegrityError,OperationalError) as exc:
            fail(exc)
    return render_template("manage.html",entity=entity,obj=obj,items=rows(model,False))


@inventory.get("/locations")
@login_required
def locations():
    term=request.args.get("q","").lower().strip()[:100]
    locs=[l for l in rows(Location) if term in " ".join([l.code,l.name,l.area,l.aisle,l.shelf,l.bin]).lower()]
    balances=[]
    for loc in locs:
        for p in rows(Product):
            qty=quantity(sid(),p.id,loc.id)
            if qty:
                balances.append((loc,p,qty))
    return render_template("locations.html",locations=locs,balances=balances)


@inventory.route("/scan",methods=["GET","POST"])
@login_required
def scan():
    mode=request.values.get("mode","lookup")
    if mode not in ("lookup","sale","receipt","transfer"):
        abort(400)
    if request.method=="POST":
        try:
            p=resolve(sid(),request.form.get("code",""))
            if request.values.get("order_id"):
                order=find(PurchaseOrder,whole(request.values["order_id"],1))
                if p.id not in {i.product_id for i in order.items}:
                    raise DomainError("Product is not a line on this order.")
                flash(f"Matched {p.name}. Confirm every line on the complete order to receive stock.","success")
                return redirect(url_for("orders.order_detail",ident=order.id))
            if mode=="lookup":
                return redirect(url_for("catalog.product_detail",ident=p.id))
            return redirect(url_for("inventory.action",kind=mode,product_id=p.id))
        except DomainError as exc:
            fail(exc)
    order_id=request.values.get("order_id")
    if order_id:
        find(PurchaseOrder,whole(order_id,1))
    return render_template("scan.html",mode=mode,order_id=order_id)


@inventory.route("/inventory/<kind>",methods=["GET","POST"])
@login_required
def action(kind):
    if kind not in ("sale","receipt","transfer"):
        abort(404)
    product_id=request.values.get("product_id")
    product=find(Product,whole(product_id,1),True) if product_id else None
    if request.method=="POST":
        try:
            if not product:
                raise DomainError("Choose a product.")
            payload={"product_id":product.id,"quantity":whole(request.form.get("quantity"),1),
                "location_id":whole(request.form.get("location_id"),1),"reason":text_field("reason",250,False)}
            if kind=="transfer":
                payload["destination_id"]=whole(request.form.get("destination_id"),1)
            loc=scoped(Location,payload["location_id"],sid(),True)
            if kind=="receipt" and not payload["reason"]:
                raise DomainError("Enter a supplier/delivery reference.")
            before=quantity(sid(),product.id,loc.id)
            if kind in ("sale","transfer") and payload["quantity"]>before and request.form.get("confirm")!="yes":
                raise DomainError("Insufficient stock at the selected location.")
            if kind=="transfer":
                dest=scoped(Location,payload["destination_id"],sid(),True)
                if dest.id==loc.id:
                    raise DomainError("Choose different source and destination locations.")
            if request.form.get("confirm")=="yes":
                result=execute(current_user,kind,payload,request.form.get("token"))
                flash(("Already recorded; stock was not changed again." if result["duplicate"] else "Inventory saved.")+f" Current product total: {quantity(sid(),product.id)} {product.unit}.","success")
                return redirect(url_for("catalog.product_detail",ident=product.id))
            changes=[(loc,before,before+(-payload["quantity"] if kind in ("sale","transfer") else payload["quantity"]))]
            if kind=="transfer":
                qty=quantity(sid(),product.id,dest.id)
                changes.append((dest,qty,qty+payload["quantity"]))
            return render_template("confirm.html",kind=kind,product=product,payload=payload,
                changes=changes,token=request.form.get("token"),total=quantity(sid(),product.id))
        except (DomainError,IntegrityError,OperationalError) as exc:
            fail(exc)
    return render_template("action.html",kind=kind,product=product,products=rows(Product),locations=rows(Location),
        balances={l.id:quantity(sid(),product.id,l.id) for l in rows(Location)} if product else {},token=request.form.get("token") or uuid4().hex)


@inventory.route("/refills",methods=["GET","POST"])
@login_required
def refills():
    if request.method=="POST":
        if current_user.role!="owner":
            abort(403)
        try:
            lock_store(current_user,True)
            p=whole(request.form.get("product_id"),1)
            shelf=whole(request.form.get("shelf_id"),1)
            source=whole(request.form.get("source_id"),1)
            scoped(Product,p,sid(),True)
            dest=scoped(Location,shelf,sid(),True)
            src=scoped(Location,source,sid(),True)
            if shelf==source or dest.kind!="shelf" or src.kind!="backroom":
                raise DomainError("Choose a sales shelf and a different backroom location.")
            rule=db.session.scalar(select(ShelfRule).where(ShelfRule.store_id==sid(),ShelfRule.product_id==p,ShelfRule.shelf_id==shelf))
            if not rule:
                rule=ShelfRule(store_id=sid(),product_id=p,shelf_id=shelf,source_id=source,target=0)
                db.session.add(rule)
            rule.source_id,rule.target=source,whole(request.form.get("target"))
            db.session.commit()
            flash("Shelf target saved.","success")
            return redirect(url_for("inventory.refills"))
        except (DomainError,IntegrityError,OperationalError) as exc:
            fail(exc)
    return render_template("refills.html",refills=shelf_refills(sid()),products=rows(Product),locations=rows(Location))


@inventory.post("/refills/<int:ident>/delete")
@owner_required
def delete_rule(ident):
    lock_store(current_user,True)
    db.session.delete(find(ShelfRule,ident))
    db.session.commit()
    flash("Shelf rule removed.","success")
    return redirect(url_for("inventory.refills"))


@inventory.route("/counts",methods=["GET","POST"])
@login_required
def counts():
    if request.method=="GET" and request.args.get("individual")!="1":
        from .reviews import list_reviews
        return list_reviews()
    if request.method=="POST":
        try:
            submit_count(current_user,whole(request.form.get("product_id"),1),whole(request.form.get("location_id"),1),request.form.get("counted_quantity"),text_field("reason",250))
            flash("Count submitted for owner approval.","success")
            return redirect(url_for("inventory.counts"))
        except (DomainError,IntegrityError,OperationalError) as exc:
            fail(exc)
    return render_template("counts.html",counts=rows(StockCountRequest,False),products=rows(Product),locations=rows(Location),
        product_map={p.id:p for p in rows(Product,False)},location_map={l.id:l for l in rows(Location,False)},token=uuid4().hex)


@inventory.post("/counts/<int:ident>/<decision>")
@owner_required
def count_decision(ident,decision):
    find(StockCountRequest,ident)
    try:
        if decision=="approve":
            execute(current_user,"adjustment",{"count_id":ident},request.form.get("token"))
        elif decision=="reject":
            lock_store(current_user,True)
            count=find(StockCountRequest,ident)
            if count.status!="pending":
                raise DomainError("Count is no longer pending.")
            count.status,count.approver_id="rejected",current_user.id
            db.session.commit()
        else:
            abort(404)
        flash("Count reviewed.","success")
    except (DomainError,IntegrityError,OperationalError) as exc:
        fail(exc)
    return redirect(url_for("inventory.counts"))


@orders.route("/reorder",methods=["GET","POST"])
@login_required
def reorder():
    if request.method=="POST":
        if current_user.role!="owner":
            abort(403)
        try:
            selected={whole(v,1) for v in request.form.getlist("product_ids")}
            if not selected:
                raise DomainError("Select at least one product to order.")
            created=create_drafts(current_user,whole(request.form.get("destination_id"),1),selected)
            flash(f"Created {len(created)} supplier draft(s). Review before approval.","success")
            return redirect(url_for("orders.order_list"))
        except (DomainError,IntegrityError,OperationalError) as exc:
            fail(exc)
    return render_template("reorder.html",recommendations=recommendations(sid()),locations=rows(Location))


@orders.get("/orders")
@login_required
def order_list():
    return render_template("orders.html",orders=list(reversed(rows(PurchaseOrder,False))),suppliers={s.id:s for s in rows(Supplier,False)})


@orders.route("/orders/<int:ident>",methods=["GET","POST"])
@login_required
def order_detail(ident):
    order=find(PurchaseOrder,ident)
    if request.method=="POST":
        action=request.form.get("action")
        try:
            if action=="receive":
                if request.form.get("confirm")!="yes":
                    raise DomainError("Confirm the complete delivery before receiving this order.")
                result=execute(current_user,"order_receipt",{"order_id":ident},request.form.get("token"))
                flash("Already received; no duplicate stock added." if result["duplicate"] else "Complete order received.","success")
            else:
                if current_user.role!="owner":
                    abort(403)
                edits={str(i.id):{"quantity":request.form.get(f"qty_{i.id}",i.quantity),"destination_id":request.form.get(f"dest_{i.id}",i.destination_id)} for i in order.items}
                change_order(current_user,ident,action,edits if action in ("edit","approve") else None,request.form.get("override_reason",""))
                flash("Order updated.","success")
            return redirect(url_for("orders.order_detail",ident=ident))
        except (DomainError,IntegrityError,OperationalError) as exc:
            fail(exc)
    current={r["product"].id:r for r in recommendations(sid())}
    return render_template("order_detail.html",order=order,supplier=find(Supplier,order.supplier_id),
        products={p.id:p for p in rows(Product,False)},locations=rows(Location),location_map={l.id:l for l in rows(Location,False)},
        source_document=db.session.scalar(select(DocumentImport).where(DocumentImport.store_id==sid(),DocumentImport.order_id==ident)),recommendations=current,current_balances={i.id:quantity(sid(),i.product_id,i.destination_id) for i in order.items},token=request.form.get("token") or uuid4().hex)


@orders.post("/orders/<int:ident>/check-line")
@login_required
def check_line(ident):
    order=find(PurchaseOrder,ident)
    try:
        p=resolve(sid(),request.form.get("code",""))
        if p.id not in {i.product_id for i in order.items}:
            raise DomainError("Product is not a line on this order.")
        flash(f"Matched {p.name}. Check quantity and destination, then confirm the complete order below.","success")
    except DomainError as exc:
        fail(exc)
    return redirect(url_for("orders.order_detail",ident=ident))


def csv_safe(value):
    text=str(value)
    if text.lstrip().startswith(("=","+","-","@")) or text.startswith(("\t","\r","\n")):
        return "'"+text
    return text


def csv_response(name,columns,data):
    output=StringIO(newline="")
    writer=csv.writer(output)
    writer.writerow(columns)
    for row in data:
        writer.writerow([csv_safe(v) if isinstance(v,str) else v for v in row])
    return current_app.response_class(output.getvalue(),mimetype="text/csv",headers={"Content-Disposition":f'attachment; filename="stocksense-{name}.csv"'})


@exports.get("/exports/<kind>.csv")
@owner_required
def export(kind):
    if kind=="inventory":
        data=[]
        for p in rows(Product,False):
            has_stock=False
            for l in rows(Location,False):
                q=quantity(sid(),p.id,l.id)
                if q:
                    has_stock=True
                    data.append([p.sku,p.name,p.unit,l.code,q,p.cost_cents,p.price_cents,q*p.cost_cents])
            if not has_stock:
                data.append([p.sku,p.name,p.unit,"",0,p.cost_cents,p.price_cents,0])
        return csv_response(kind,["SKU","Product","Unit","Location","Quantity","Unit cost cents","Price cents","Stock value cents"],data)
    if kind=="reorder":
        return csv_response(kind,["SKU","Product","Supplier","Stock","Average daily sales","Coverage days","Forecast target","Threshold","Approved incoming","Suggested units","Unit cost cents"],
            [[r["product"].sku,r["product"].name,r["supplier"].name,r["stock"],r["average"],r["coverage"],r["forecast"],r["threshold"],r["incoming"],r["suggested"],r["product"].cost_cents] for r in recommendations(sid())])
    if kind=="sales":
        try:
            data=report(sid(),request.args.get("start"),request.args.get("end"))
        except DomainError:
            abort(400)
        return csv_response(kind,["Start date","End date","Business timezone","Sale ID","UTC timestamp","SKU","Product","Source location ID","Units","Price snapshot cents","Revenue cents"],
            [[data["start"],data["end"],data["timezone"],s.id,s.effective_at.isoformat(),data["products"][s.product_id].sku,data["products"][s.product_id].name,s.location_id,s.quantity,s.price_cents,s.quantity*s.price_cents] for s in data["sales"]])
    abort(404)


@exports.get("/orders/<int:ident>/export.csv")
@owner_required
def order_export(ident):
    order=find(PurchaseOrder,ident)
    supplier=find(Supplier,order.supplier_id)
    return csv_response(f"order-{ident}",["Order","Status","Supplier","SKU","Product","Destination","Quantity","Unit cost cents","Line total cents"],
        [[ident,order.status,supplier.name,find(Product,i.product_id).sku,find(Product,i.product_id).name,find(Location,i.destination_id).code,i.quantity,i.cost_cents,i.quantity*i.cost_cents] for i in order.items])
