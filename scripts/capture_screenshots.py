"""Capture actual local application screens, never mock report screenshots."""
from pathlib import Path
from dotenv import dotenv_values
from playwright.sync_api import sync_playwright

root=Path(__file__).resolve().parents[1]
output=root/'docs'/'screenshots';output.mkdir(exist_ok=True)
config=dotenv_values(root/'.env')
with sync_playwright() as p:
    browser=p.chromium.launch(channel='chrome')
    page=browser.new_page(viewport={'width':1440,'height':1050},device_scale_factor=1)
    errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto('http://127.0.0.1:5050/login')
    page.get_by_label('Email address').fill('owner@stocksense.test')
    page.get_by_label('Password',exact=True).fill(config['DEMO_OWNER_PASSWORD'])
    page.get_by_role('button',name='Sign in',exact=False).click()
    page.wait_for_url('http://127.0.0.1:5050/')
    for name,path in [('overview','/'),('products','/products'),('scanner','/scan?mode=sale'),('locations','/locations'),('reorder','/reorder'),('refills','/refills'),('product','/products/1'),('imports','/imports'),('stocktakes','/counts')]:
        page.goto('http://127.0.0.1:5050'+path);page.wait_for_load_state('networkidle');page.screenshot(path=str(output/(name+'.png')),full_page=True);page.screenshot(path=str(output/(name+'-report.png')),full_page=False)
    page.set_viewport_size({'width':390,'height':844});page.goto('http://127.0.0.1:5050/scan?mode=sale')
    page.screenshot(path=str(output/'mobile-scanner.png'),full_page=True)
    assert not errors,errors
    browser.close()
print('Captured current application screens, including imports and stock reviews. No JavaScript page errors.')
