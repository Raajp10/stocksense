# Render deployment and persistence

The application uses Flask/Python 3.12 and PostgreSQL; it cannot run as a static Site or a JavaScript Cloudflare Worker. The available Sites hosting workflow is therefore unsuitable for this approved stack. `render.yaml` is the concrete Render deployment configuration. No Render service is claimed until a successful service response and runtime check exist.

1. Connect the public GitHub repository in Render, review current pricing, and create a Blueprint using `render.yaml`. The proposed web service, PostgreSQL and media disk are paid resources; do not provision them without accepting the current cost. Official references: https://render.com/docs/deploy-flask , https://render.com/docs/blueprint-spec , https://render.com/docs/disks , https://render.com/docs/deploys . Checked October 28, 2026.
2. Keep PostgreSQL `DATABASE_URL` generated from the database, random `SECRET_KEY`, `APP_ENV=production`, and `UPLOAD_DIR=/var/data/uploads`. The attached persistent disk survives process replacement/redeployments; the source directory is not a durable upload location.
3. Build installs pinned runtime requirements. Start migrates then launches Gunicorn on `$PORT`. One service instance with a disk is the intended topology. Migration before startup is suitable here; use a dedicated migration release step before scaling.
4. Configure **After CI Checks Pass** (`autoDeployTrigger: checksPass`). Ensure the repository's verification job runs all required checks; do not allow skipped checks to stand in for executed tests. The initial Blueprint deployment still needs a verified commit and passing tests before exposure.
5. Configure demo passwords as temporary service secrets, run `flask --app app seed-demo` in Render's shell once against an empty database, then remove those environment values. Use fictional records. No public registration exists. Never publish an owner's password.
6. Verify `/health`, sign-in, owner/staff permissions, sale → transfer → order → receipt, and `flask --app app reconcile` on PostgreSQL. Upload a new photo, restart and redeploy, then verify the same photo bytes and balances. Run a real-device HTTPS camera smoke test.
7. Confirm database backup/retention for the selected plan and separately back up the media disk. Restore to an isolated environment and reconcile. Cost and storage guarantees vary by plan; verify against current Render documentation before purchase.

## Local production smoke test

Set a temporary PostgreSQL database and absolute media directory, migrate and seed with environment-supplied passwords, then launch `gunicorn 'app:create_app()' --bind 127.0.0.1:5051`. For a true production-cookie check use HTTPS; `SESSION_COOKIE_SECURE` intentionally prevents plain-HTTP production sessions. The local development demo uses localhost with APP_ENV unset.

## Release evidence

A green local PostgreSQL suite proves tested SQL behavior on that local version, not Render's network/proxy/disk lifecycle. The release checklist records unverified hosted steps separately. Actual provisioning requires an authenticated Render account and acceptance of the selected resources' cost.
