import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
import click
from sqlalchemy import select
from werkzeug.security import generate_password_hash
from PIL import Image, ImageDraw, ImageFont
from .extensions import db
from .models import Store, User, Supplier, Location, Product, ShelfRule, Sale, PurchaseOrder, PurchaseOrderItem, now
from .services.inventory import execute, reconciliation
from .services.reorder import utc_bounds


def fixture_photo(directory, index, name):
    """Original geometric package illustrations generated locally, no external assets."""
    colors=[('#e4e8d5','#6d8150'),('#e4ddce','#8e7755'),('#e5d8cd','#aa7b59'),('#dce6df','#628674')]
    bg,fg=colors[index%len(colors)]
    image=Image.new('RGB',(480,400),bg)
    draw=ImageDraw.Draw(image)
    draw.ellipse((120,330,370,370),fill='#d1d5c5')
    draw.rounded_rectangle((160,85,330,342),radius=16,fill='#fffdf4',outline=fg,width=3)
    draw.polygon([(160,85),(195,40),(295,40),(330,85)],fill=fg)
    draw.rectangle((190,42,300,61),fill='#f5f2e7')
    draw.rectangle((160,145,330,266),fill=fg)
    draw.text((181,165),'STOCKSENSE',fill='white',font_size=19)
    words=name.upper().split()
    for n,word in enumerate(words[:3]):
        draw.text((180,195+n*22),word[:13],fill='white',font_size=17)
    draw.text((202,293),'1 UNIT',fill=fg,font_size=17)
    key=f'{index+1:032x}.jpg'
    image.save(Path(directory)/key,quality=90)
    return key


def seed(app, reference=None):
    owner_password=os.getenv('DEMO_OWNER_PASSWORD','')
    staff_password=os.getenv('DEMO_STAFF_PASSWORD','')
    if min(len(owner_password),len(staff_password))<10:
        raise click.ClickException('Set DEMO_OWNER_PASSWORD and DEMO_STAFF_PASSWORD to at least 10 characters.')
    if db.session.scalar(select(Store.id).limit(1)):
        raise click.ClickException('Database already contains a store. Seed is intentionally non-destructive; use a fresh database.')
    today=datetime.strptime(reference,'%Y-%m-%d').date() if reference else datetime.now(timezone.utc).astimezone(__import__('zoneinfo').ZoneInfo('America/Chicago')).date()
    store=Store(name='The Corner Café',timezone='America/Chicago')
    db.session.add(store);db.session.flush()
    owner=User(store_id=store.id,email='owner@stocksense.test',name='Raaj Patel',role='owner',password_hash=generate_password_hash(owner_password))
    staff=User(store_id=store.id,email='staff@stocksense.test',name='Jamie Lee',role='staff',password_hash=generate_password_hash(staff_password))
    db.session.add_all([owner,staff]);db.session.flush()
    suppliers=[Supplier(store_id=store.id,name=name,contact='demo@'+domain+'.test',lead_time_days=lead,safety_days=2) for name,domain,lead in [('Midwest Dairy','midwest',3),('CupCo Supplies','cupco',5),('Sunrise Pantry','sunrise',2)]]
    db.session.add_all(suppliers)
    shelf=Location(store_id=store.id,code='A-02',name='Shelf A-02',kind='shelf',area='Sales floor',aisle='A',shelf='02',bin='Front')
    back=Location(store_id=store.id,code='B-04',name='Backroom B-04',kind='backroom',area='Backroom',aisle='B',shelf='04',bin='Reserve')
    fridge=Location(store_id=store.id,code='F-01',name='Fridge F-01',kind='general',area='Counter',aisle='F',shelf='01',bin='Cold')
    db.session.add_all([shelf,back,fridge]);db.session.flush()
    names=['Oat milk','Almond milk','Whole milk','12 oz cups','12 oz lids','Paper napkins','Coffee beans','Earl Grey tea','Cocoa powder','Vanilla syrup','Caramel syrup','Sugar sachets','Croissants','Granola bars','Sparkling water','Orange juice','New seasonal blend','Gift cards']
    products=[]
    for i,name in enumerate(names):
        supplier=suppliers[0 if i<3 else 1 if i<6 else 2]
        created=utc_bounds(today-timedelta(days=45 if i!=16 else 0),today,store.timezone)[0]
        p=Product(store_id=store.id,supplier_id=supplier.id,name=name,sku='OAT-001' if i==0 else f'SKU-{i+1:03}',
            description=f'{name} for the café. Count each sealed retail unit separately; use the printed SKU label to record stock.',
            category='Dairy alternatives' if i<3 else 'Supplies' if i<6 else 'Pantry',
            unit='carton' if i<3 else 'unit',cost_cents=350 if i==0 else 80+(i*37)%600,
            price_cents=550 if i==0 else 150+(i*53)%1000,reorder_level=5 if i==0 else 10,
            created_at=created,image_key=fixture_photo(app.config['UPLOAD_DIR'],i,name))
        db.session.add(p);products.append(p)
    db.session.commit()
    for i,p in enumerate(products):
        if i==0:
            # 180 historical units + current 8. Reclassify history timestamps below.
            execute(owner,'opening',dict(product_id=p.id,location_id=shelf.id,quantity=183),f'seed_opening_{i:020}')
            execute(owner,'receipt',dict(product_id=p.id,location_id=back.id,quantity=5,reason='Seed backroom stock'),f'seed_backroom_{i:019}')
            for day in range(30,0,-1):
                result=execute(owner,'sale',dict(product_id=p.id,location_id=shelf.id,quantity=6),f'seed_sale_{i:03}_{day:020}')
                sale=db.session.scalar(select(Sale).where(Sale.operation_id==result['operation_id']))
                lo,_=utc_bounds(today-timedelta(days=day),today,store.timezone)
                sale.effective_at=lo+timedelta(hours=12)
                db.session.commit()
        else:
            daily=0 if i in (16,17) else (i%4)+1
            end_stock=4 if i==1 else 18+i*3
            execute(owner,'opening',dict(product_id=p.id,location_id=shelf.id,quantity=end_stock+daily*30),f'seed_opening_{i:020}')
            execute(owner,'receipt',dict(product_id=p.id,location_id=back.id,quantity=15+i,reason='Seed backroom stock'),f'seed_backroom_{i:019}')
            if daily:
                for day in range(30,0,-1):
                    result=execute(owner,'sale',dict(product_id=p.id,location_id=shelf.id,quantity=daily),f'seed_sale_{i:03}_{day:020}')
                    sale=db.session.scalar(select(Sale).where(Sale.operation_id==result['operation_id']))
                    lo,_=utc_bounds(today-timedelta(days=day),today,store.timezone)
                    sale.effective_at=lo+timedelta(hours=12+i%5)
                    db.session.commit()
    db.session.add(ShelfRule(store_id=store.id,product_id=products[0].id,shelf_id=shelf.id,source_id=back.id,target=5))
    # Demonstrate both order states without affecting the oat-milk example.
    products[1].reorder_level=35
    for status,product,qty in [('approved',products[1],10),('draft',products[3],7)]:
        order=PurchaseOrder(store_id=store.id,supplier_id=product.supplier_id,
            status=status,created_by=owner.id,approved_by=owner.id if status=='approved' else None,
            approved_at=now() if status=='approved' else None)
        db.session.add(order);db.session.flush()
        db.session.add(PurchaseOrderItem(store_id=store.id,order_id=order.id,product_id=product.id,
            destination_id=back.id,quantity=qty,cost_cents=product.cost_cents))
    # A separate store is deliberately present to exercise isolation.
    other=Store(name='Isolation Test Store',timezone='America/Chicago')
    db.session.add(other);db.session.flush()
    db.session.add(User(store_id=other.id,email='other@stocksense.test',name='Other Owner',role='owner',password_hash=generate_password_hash(owner_password)))
    db.session.commit()
    if reconciliation(store.id):
        raise click.ClickException('Seed reconciliation failed.')
    click.echo(f'Seeded 18 products, 3 suppliers, 3 locations, 30 days of synthetic sales. Reference date: {today}.')
    click.echo('Owner: owner@stocksense.test; staff: staff@stocksense.test. Passwords are your environment values.')


def register_commands(app):
    @app.cli.command('seed-demo')
    @click.option('--reference-date',default=None,help='YYYY-MM-DD, for reproducible calculation fixtures.')
    def seed_demo(reference_date):
        seed(app,reference_date)

    @app.cli.command('reconcile')
    def reconcile():
        problems=[]
        for store in db.session.scalars(select(Store)):
            problems.extend(reconciliation(store.id))
        if problems:
            raise click.ClickException(str(problems))
        click.echo('All location balances reconcile with the stock movement ledger.')
