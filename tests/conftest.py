import os
from datetime import timedelta
import pytest
from werkzeug.security import generate_password_hash
from flask_migrate import upgrade
from sqlalchemy import select
from app import create_app
from app.extensions import db
from app.models import Store, User, Supplier, Product, Location, ShelfRule, now
from app.services.inventory import execute


@pytest.fixture
def app(tmp_path):
    url=os.getenv('TEST_DATABASE_URL',f'sqlite:///{tmp_path / "test.db"}')
    application=create_app(dict(TESTING=True,SECRET_KEY='test-only-secret',SQLALCHEMY_DATABASE_URI=url,
        UPLOAD_DIR=str(tmp_path/'uploads'),WTF_CSRF_ENABLED=False))
    with application.app_context():
        # TEST_DATABASE_URL must point at a disposable test database.
        db.drop_all()
        from sqlalchemy import text
        db.session.execute(text('DROP TABLE IF EXISTS alembic_version'))
        db.session.commit()
        upgrade()
        stores=[Store(name='Test café'),Store(name='Other store')]
        db.session.add_all(stores);db.session.flush()
        users=[User(store_id=stores[0].id,email='owner@test.test',name='Owner',role='owner',password_hash=generate_password_hash('test-password')),
               User(store_id=stores[0].id,email='staff@test.test',name='Staff',role='staff',password_hash=generate_password_hash('test-password')),
               User(store_id=stores[1].id,email='other@test.test',name='Other',role='owner',password_hash=generate_password_hash('test-password'))]
        db.session.add_all(users)
        suppliers=[Supplier(store_id=s.id,name='Supplier',lead_time_days=3,safety_days=2) for s in stores]
        db.session.add_all(suppliers);db.session.flush()
        locations=[Location(store_id=stores[0].id,code='A-02',name='Shelf',kind='shelf'),Location(store_id=stores[0].id,code='B-04',name='Backroom',kind='backroom'),Location(store_id=stores[1].id,code='X',name='Other',kind='general')]
        db.session.add_all(locations)
        products=[Product(store_id=s.id,supplier_id=supplier.id,sku='OAT-001',name='Oat milk',cost_cents=350,price_cents=550,reorder_level=5,created_at=now()-timedelta(days=45)) for s,supplier in zip(stores,suppliers)]
        db.session.add_all(products);db.session.flush()
        db.session.add(ShelfRule(store_id=stores[0].id,product_id=products[0].id,shelf_id=locations[0].id,source_id=locations[1].id,target=5))
        db.session.commit()
        execute(users[0],'opening',dict(product_id=products[0].id,location_id=locations[0].id,quantity=3),'opening_test_00000001')
        execute(users[0],'receipt',dict(product_id=products[0].id,location_id=locations[1].id,quantity=5,reason='Fixture delivery'),'receipt_test_00000001')
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def owner(app):
    return db.session.scalar(select(User).where(User.email=='owner@test.test'))


@pytest.fixture
def product(app):
    return db.session.scalar(select(Product).where(Product.store_id==1))


@pytest.fixture
def signed_in(client):
    response=client.post('/login',data={'email':'owner@test.test','password':'test-password'})
    assert response.status_code==302
    return client
