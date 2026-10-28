import threading
import pytest
from werkzeug.serving import make_server
from playwright.sync_api import expect
from app.extensions import db
from app.models import Product
from app.services.inventory import quantity,reconciliation

pytestmark=pytest.mark.e2e


@pytest.fixture
def live_url(app):
    server=make_server('127.0.0.1',0,app,threaded=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    yield f'http://127.0.0.1:{server.server_port}'
    server.shutdown();thread.join(timeout=5)


def login(page,url,staff=False):
    page.goto(url+'/login')
    page.get_by_label('Email address').fill('staff@test.test' if staff else 'owner@test.test')
    page.get_by_label('Password',exact=True).fill('test-password')
    page.get_by_role('button',name='Sign in',exact=False).click()
    expect(page.get_by_role('heading',name='Good stock. Better days.')).to_be_visible()
    assert page.evaluate("!!Chart.getChart(document.getElementById('sales-chart'))")


def test_owner_end_to_end(page,live_url):
    login(page,live_url)
    page.goto(live_url+'/scan?mode=sale')
    page.get_by_label('SKU or StockSense QR payload').fill('OAT-001')
    page.get_by_role('button',name='Find product').click()
    page.get_by_label('Quantity').fill('2')
    page.get_by_label('Source location').select_option('1')
    page.get_by_role('button',name='Review sale').click()
    expect(page.get_by_role('heading',name='Confirm sale')).to_be_visible()
    page.get_by_role('button',name='Confirm sale').click()
    expect(page.get_by_role('alert')).to_contain_text('Current product total: 6')
    page.goto(live_url+'/refills')
    page.get_by_role('link',name='Review move').click()
    page.get_by_role('button',name='Review transfer').click()
    page.get_by_role('button',name='Confirm transfer').click()
    expect(page.get_by_role('alert')).to_contain_text('Current product total: 6')
    # Raise the manual threshold so a no-history fixture suggests a real order.
    page.goto(live_url+'/products/1/edit')
    page.get_by_label('Reorder level').fill('30')
    page.get_by_role('button',name='Save product').click()
    page.goto(live_url+'/reorder')
    page.get_by_label('Default receiving location').select_option('2')
    page.get_by_role('button',name='Create supplier drafts').click()
    page.get_by_role('link',name='View order').first.click()
    page.get_by_role('button',name='Approve order').click()
    page.get_by_label('SKU or QR payload').fill('OAT-001')
    page.get_by_role('button',name='Check line').click()
    expect(page.get_by_role('alert')).to_contain_text('Matched Oat milk')
    page.get_by_label('I checked every quantity').check()
    page.get_by_role('button',name='Receive complete order').click()
    expect(page.get_by_role('alert')).to_contain_text('Complete order received')
    expect(page.get_by_role('button',name='Receive complete order')).to_have_count(0)
    page.goto(live_url+'/products/1')
    expect(page.locator('.stock-total')).to_contain_text('30')


def test_staff_denial_and_mobile(page,live_url):
    page.set_viewport_size({'width':390,'height':844})
    login(page,live_url,staff=True)
    expect(page.get_by_role('link',name='Team access')).to_have_count(0)
    response=page.goto(live_url+'/products/1/edit')
    assert response.status==403
    for path in ['/','/products','/scan','/locations','/refills','/reorder','/orders','/counts']:
        page.goto(live_url+path)
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'),path


def test_camera_denial_fallback(page,live_url):
    page.add_init_script("Object.defineProperty(navigator.mediaDevices,'getUserMedia',{value:()=>Promise.reject(new DOMException('Denied','NotAllowedError'))});")
    login(page,live_url)
    page.goto(live_url+'/scan?mode=sale')
    page.get_by_role('button',name='Start camera').click()
    expect(page.get_by_role('status')).to_contain_text('permission was denied')
    page.get_by_label('SKU or StockSense QR payload').fill('OAT-001')
    page.get_by_role('button',name='Find product').click()
    expect(page.get_by_role('heading',name='Record a sale')).to_be_visible()


def test_actual_decoder_with_synthetic_video_no_stock_writes(page,live_url):
    # This exercises the real vendored QR decoder on a generated video stream.
    # It does not claim to test a physical camera, lighting or permissions.
    page.add_init_script("""Object.defineProperty(navigator.mediaDevices,'getUserMedia',{value:async()=>{
       const image=new Image();image.src='/products/1/qr.png';await image.decode();
       const canvas=document.createElement('canvas');canvas.width=640;canvas.height=480;
       const context=canvas.getContext('2d');const draw=()=>{context.fillStyle='white';context.fillRect(0,0,640,480);context.drawImage(image,120,40,400,400);};
       draw();setInterval(draw,50);return canvas.captureStream(20);
    }});""")
    login(page,live_url)
    page.goto(live_url+'/scan?mode=sale')
    page.get_by_role('button',name='Start camera').click()
    expect(page.get_by_role('heading',name='Record a sale')).to_be_visible(timeout=15000)
    page.goto(live_url+'/products/1')
    expect(page.locator('.stock-total')).to_contain_text('8')


def test_owner_catalog_photo_location_and_staff_setup(page,live_url,tmp_path):
    from PIL import Image
    login(page,live_url)
    page.goto(live_url+'/manage/suppliers')
    page.get_by_label('Name',exact=True).fill('New supplier')
    page.get_by_label('Contact').fill('hello@supplier.test')
    page.get_by_role('button',name='Save supplier').click()
    expect(page.get_by_text('Saved successfully.')).to_be_visible()
    page.goto(live_url+'/manage/locations')
    page.get_by_label('Name',exact=True).fill('Endcap shelf')
    page.get_by_label('Code',exact=True).fill('E-01')
    page.get_by_label('Type',exact=True).select_option('shelf')
    page.get_by_role('button',name='Save location').click()
    page.goto(live_url+'/products/new')
    page.get_by_label('Product name').fill('Demo tea')
    page.get_by_label('SKU',exact=True).fill('TEA-NEW')
    page.get_by_label('Supplier',exact=True).select_option(label='New supplier')
    page.get_by_label('Description').fill('A product added during a browser workflow.')
    page.get_by_label('Opening quantity').fill('7')
    page.get_by_label('Opening stock location').select_option(label='E-01 · Endcap shelf')
    page.get_by_role('button',name='Save product').click()
    expect(page.locator('.stock-total')).to_contain_text('7')
    photo=tmp_path/'photo.png';Image.new('RGB',(100,80),'green').save(photo)
    page.get_by_label('Product photo',exact=True).set_input_files(str(photo))
    page.get_by_role('button',name='Save photo').click()
    expect(page.get_by_role('alert')).to_contain_text('Photo saved')
    page.get_by_role('link',name='Print QR label').click()
    expect(page.locator('.qr-label')).to_contain_text('TEA-NEW')
    page.goto(live_url+'/manage/staff')
    page.get_by_label('Name',exact=True).fill('New staff')
    page.get_by_label('Email',exact=True).fill('new@staff.test')
    page.get_by_label('Password',exact=True).fill('new-test-password')
    page.get_by_role('button',name='Save team member').click()
    expect(page.get_by_text('new@staff.test',exact=False)).to_be_visible()
