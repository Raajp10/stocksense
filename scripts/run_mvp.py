"""Prepare and launch the local prototype without a hosting account."""
import argparse
import os
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from dotenv import load_dotenv
from flask_migrate import upgrade
from sqlalchemy import select
from app import create_app
from app.cli import seed
from app.extensions import db
from app.models import Store
from app.services.inventory import reconciliation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=5050)
    parser.add_argument('--check', action='store_true', help='Prepare and verify without starting the server')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('Port must be between 1 and 65535.')
    env_file = ROOT / '.env'
    if not env_file.exists():
        with env_file.open('x', encoding='utf-8') as target:
            target.write('SECRET_KEY=' + secrets.token_hex(32) + '\n')
            target.write('DEMO_OWNER_PASSWORD=' + secrets.token_urlsafe(18) + '\n')
            target.write('DEMO_STAFF_PASSWORD=' + secrets.token_urlsafe(18) + '\n')
        env_file.chmod(0o600)
        print('Created private local credentials in .env.', flush=True)
    load_dotenv(env_file)
    if os.getenv('APP_ENV') == 'production':
        parser.error('This launcher is for the local MVP. Use the documented production start command for hosting.')
    app = create_app()
    print('Preparing the local prototype; existing data will be retained.', flush=True)
    with app.app_context():
        upgrade(directory=str(ROOT / 'migrations'))
        if db.session.scalar(select(Store.id).limit(1)) is None:
            seed(app)
        for store in db.session.scalars(select(Store)):
            if reconciliation(store.id):
                raise RuntimeError('Stock does not reconcile. Review the ledger before continuing.')
    print('Local MVP ready. Owner: owner@stocksense.test; staff: staff@stocksense.test.', flush=True)
    print('New demo passwords: DEMO_OWNER_PASSWORD / DEMO_STAFF_PASSWORD in your environment or private .env file.', flush=True)
    print('Existing accounts retain their original passwords.', flush=True)
    if not args.check:
        app.run(host='127.0.0.1', port=args.port, debug=False, use_reloader=False)


if __name__ == '__main__':
    main()
