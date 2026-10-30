import threading
import os
from pathlib import Path
import pytest
from werkzeug.serving import make_server
from playwright.sync_api import expect
from app.extensions import db
from app.models import Product
from app.services.inventory import quantity,reconciliation

pytestmark=pytest.mark.e2e


def capture_business_screen(page,name):
    if os.getenv('CAPTURE_MVP_SCREENSHOTS')=='1':
        output=Path('docs/screenshots');output.mkdir(parents=True,exist_ok=True)
        page.screenshot(path=str(output/name),full_page=True)



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


def test_receipt_list_review_and_receive_all_lines(page,live_url):
    login(page,live_url)
    page.goto(live_url+'/imports')
    page.get_by_label('Email or receipt text').fill('Supplier: Supplier\nInvoice: BROWSER-101\nSKU,Description,Qty,Unit cost\nOAT-001,Oat milk,12,3.50\nTEA-NEW,Green tea,6,2.00')
    page.get_by_role('button',name='Find supplier & items').click()
    expect(page.get_by_role('heading',name='Check the details, together.')).to_be_visible()
    lines=page.locator('[data-import-line]')
    expect(lines).to_have_count(2)
    page.locator('#import-default-location').select_option('2')
    page.get_by_role('button',name='Apply to all rows').click()
    lines.nth(1).get_by_label('Selling price ($)',exact=True).fill('4.50')
    lines.nth(1).get_by_label('Reorder level',exact=True).fill('5')
    capture_business_screen(page,'receipt-review.png')
    page.get_by_role('button',name='Save review & continue').click()
    expect(page.get_by_role('heading',name='What should happen next?')).to_be_visible()
    page.get_by_label('I checked every product').check()
    page.get_by_role('button',name='Receive delivered goods').click()
    expect(page.get_by_role('alert')).to_contain_text('All reviewed delivery lines were received')
    expect(page.get_by_role('button',name='Receive delivered goods')).to_have_count(0)
    page.goto(live_url+'/products/1')
    expect(page.locator('.stock-total')).to_contain_text('20')
    page.goto(live_url+'/products?category=Beverages')
    expect(page.get_by_role('heading',name='Green tea')).to_be_visible()
    expect(page.get_by_role('heading',name='Oat milk')).to_have_count(0)


def test_owner_request_staff_multi_location_count_owner_approval(page,live_url,app):
    db.session.add(Product(store_id=1,supplier_id=1,sku='TEA-CNT',name='Counted tea',category='Beverages'))
    db.session.commit()
    login(page,live_url)
    page.goto(live_url+'/counts')
    page.get_by_label('Review title').fill('Annual shelf and backroom review')
    page.get_by_label('Assign to',exact=True).select_option('2')
    page.get_by_role('button',name='Select all',exact=True).click()
    page.get_by_role('button',name='Select visible',exact=True).click()
    page.get_by_role('button',name='Request count sheet').click()
    expect(page.get_by_role('heading',name='Annual shelf and backroom review')).to_be_visible()
    address=page.url
    page.get_by_role('button',name='Sign out',exact=True).click()
    login(page,live_url,staff=True);page.goto(address)
    expect(page.get_by_text('Expected baseline',exact=True)).to_have_count(0)
    inputs=page.locator('input[name^="count_"]')
    expect(inputs).to_have_count(4)
    for field,value in zip(inputs.all(),['2','1','4','0']): field.fill(value)
    page.get_by_role('button',name='Save counting progress').click()
    expect(page.locator('input[name^="count_"]').first).to_have_value('2')
    page.get_by_role('button',name='Submit all counts for review').click()
    expect(page.locator('.review-summary')).to_contain_text('Owner review needed')
    page.get_by_role('button',name='Sign out',exact=True).click()
    login(page,live_url);page.goto(address)
    capture_business_screen(page,'stock-review-variance.png')
    page.get_by_label('I reviewed the differences').check()
    page.get_by_role('button',name='Approve all location counts').click()
    expect(page.get_by_role('alert')).to_contain_text('Count sheet updated')
    page.goto(live_url+'/products/1')
    expect(page.locator('.stock-total')).to_contain_text('6')


def test_count_recount_and_print_buttons(page,live_url,owner):
    from app.services.stocktakes import create_session
    sheet=create_session(owner,'Recount request','Check a shelf',[1],[1])
    login(page,live_url)
    page.goto(live_url+f'/stocktakes/{sheet.id}')
    page.evaluate('window.print=()=>{window.printWasCalled=true;}')
    page.get_by_role('button',name='Print sheet').click()
    assert page.evaluate('window.printWasCalled')
    page.locator('input[name^="count_"]').fill('2')
    page.get_by_role('button',name='Submit all counts for review').click()
    page.get_by_label('Review / recount reason').fill('Please open the reserve box and count individual units')
    page.get_by_role('button',name='Request a fresh manual count').click()
    expect(page.locator('input[name^="count_"]')).to_have_value('')
    expect(page.get_by_text('Request a fresh manual count',exact=False)).to_have_count(0)
    expect(page.get_by_text('Recount requested',exact=False)).to_be_visible()


def test_import_add_remove_apply_location_and_mobile(page,live_url):
    login(page,live_url)
    page.goto(live_url+'/imports')
    page.get_by_label('Email or receipt text').fill('Supplier: Supplier\nOat milk 2 3.50 7.00')
    page.get_by_role('button',name='Find supplier & items').click()
    page.get_by_role('button',name='Add a missing item').click()
    expect(page.locator('[data-import-line]')).to_have_count(2)
    page.locator('#import-default-location').select_option('1')
    page.get_by_role('button',name='Apply to all rows').click()
    assert page.locator('[data-line-location]').evaluate_all('(items)=>items.every(i=>i.value==="1")')
    page.get_by_role('button',name='Remove item').last.click()
    expect(page.locator('[data-import-line]')).to_have_count(1)
    review_url=page.url
    page.set_viewport_size({'width':390,'height':844})
    for address in ['/imports','/counts','/products',review_url]:
        page.goto(address if address.startswith('http') else live_url+address)
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'),address


def test_owner_navigation_links_are_live(page,live_url):
    login(page,live_url)
    links=page.locator('nav a, .task-launchers a').evaluate_all('(items)=>items.map(a=>a.href)')
    for address in set(links):
        response=page.request.get(address)
        assert response.status==200,address


def test_photo_receipt_upload_reads_list_without_stock_writes(page,live_url,tmp_path):
    import shutil
    if not shutil.which('tesseract'): pytest.skip('Tesseract is required for photo recognition')
    from PIL import Image,ImageDraw
    image=Image.new('RGB',(1800,800),'white');draw=ImageDraw.Draw(image)
    for i,text in enumerate(['Supplier: Supplier','Invoice: PHOTO-UI','Oat milk 4 3.50 14.00','Green tea 6 2.00 12.00']):
        draw.text((60,50+i*140),text,fill='black',font_size=44)
    photo=tmp_path/'receipt.png';image.save(photo)
    login(page,live_url);page.goto(live_url+'/imports')
    page.get_by_label('Receipt / document',exact=True).set_input_files(str(photo))
    page.get_by_role('button',name='Read document').click()
    expect(page.locator('[data-import-line]')).to_have_count(2)
    expect(page.locator('input[name="line_0_quantity"]')).to_have_value('4')
    source=page.get_by_role('link',name='Open source document')
    assert page.request.get(live_url+source.get_attribute('href')).status==200
    page.goto(live_url+'/products/1')
    expect(page.locator('.stock-total')).to_contain_text('8')
