"""Rehearse install/migration/seed/start from tracked source in an isolated directory."""
import os
import subprocess
import tempfile
import shutil
import json
import urllib.request
import urllib.parse
import http.cookiejar
import re
from dotenv import dotenv_values
import time
from pathlib import Path

root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='stocksense-fresh-') as temporary:
    target=Path(temporary)
    names=subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0')
    for name in filter(None,names):
        source=root/name
        if source.is_file():
            dest=target/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)
    env=os.environ.copy()
    for key in ['DATABASE_URL','APP_ENV','SECRET_KEY','UPLOAD_DIR','DEMO_OWNER_PASSWORD','DEMO_STAFF_PASSWORD','VIRTUAL_ENV']:
        env.pop(key,None)
    env.update(UV_PROJECT_ENVIRONMENT=str(target/'.venv'))
    for args in [['uv','sync','--frozen'],['uv','run','python','scripts/run_mvp.py','--check'],['uv','run','flask','--app','app','db','check'],['uv','run','flask','--app','app','reconcile']]:
        subprocess.run(args,cwd=target,env=env,check=True)
    credentials=dotenv_values(target/'.env')
    assert len(credentials['DEMO_OWNER_PASSWORD'])>=10
    original_env=(target/'.env').read_bytes()
    subprocess.run(['uv','run','python','scripts/run_mvp.py','--check'],cwd=target,env=env,check=True)
    assert (target/'.env').read_bytes()==original_env
    env.update({k:v for k,v in credentials.items() if v is not None})
    proc=subprocess.Popen(['uv','run','gunicorn','app:create_app()','--bind','127.0.0.1:5059','--workers','2'],cwd=target,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                response=json.load(urllib.request.urlopen('http://127.0.0.1:5059/health',timeout=2))
                assert response['status']=='ok'
                break
            except (OSError,ValueError):time.sleep(.1)
        else:raise RuntimeError('Fresh application did not serve health endpoint')
        with urllib.request.urlopen('http://127.0.0.1:5059/login') as response:
            assert response.status==200 and b'Sign in to your store' in response.read()
        opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        html=opener.open('http://127.0.0.1:5059/login').read().decode()
        csrf=re.search(r'name="csrf_token" value="([^"]+)"',html).group(1)
        body=urllib.parse.urlencode({'email':'owner@stocksense.test','password':credentials['DEMO_OWNER_PASSWORD'],'csrf_token':csrf}).encode()
        with opener.open('http://127.0.0.1:5059/login',data=body) as response:
            assert 'Good stock. Better days.' in response.read().decode()
    finally:
        proc.terminate();proc.wait(timeout=10)
print('Fresh MVP launcher, generated private credentials, repeat startup, migration, seed, reconciliation and two-worker Gunicorn authenticated login: PASSED.')
