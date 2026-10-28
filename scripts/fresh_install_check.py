"""Rehearse install/migration/seed/start from tracked source in an isolated directory."""
import os
import subprocess
import tempfile
import shutil
import secrets
import json
import urllib.request
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
    for key in ['DATABASE_URL','APP_ENV','SECRET_KEY','UPLOAD_DIR','DEMO_OWNER_PASSWORD','DEMO_STAFF_PASSWORD']:
        env.pop(key,None)
    env.update(SECRET_KEY=secrets.token_hex(32),DEMO_OWNER_PASSWORD=secrets.token_urlsafe(18),DEMO_STAFF_PASSWORD=secrets.token_urlsafe(18),UV_PROJECT_ENVIRONMENT=str(target/'.venv'))
    for args in [['uv','sync','--frozen'],['uv','run','flask','--app','app','db','upgrade'],['uv','run','flask','--app','app','db','check'],['uv','run','flask','--app','app','seed-demo'],['uv','run','flask','--app','app','reconcile']]:
        subprocess.run(args,cwd=target,env=env,check=True)
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
    finally:
        proc.terminate();proc.wait(timeout=10)
print('Fresh tracked-source installation, empty migration, seed, reconciliation, two-worker Gunicorn health and login: PASSED.')
