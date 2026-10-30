# Verification evidence — October 28, 2026

Environment: macOS x86_64, CPython 3.12.14, locked Python dependencies, SQLite and PostgreSQL 14.18. Browser: Playwright 1.64.1 Chromium (plus an initial run through installed Chrome). Test databases and records are disposable and synthetic.

| Command / check | Actual result | Evidence |
|---|---|---|
| `uv run pytest --ignore=tests/e2e -q --junitxml=docs/evidence-sqlite.xml` | 57 passed | `evidence-sqlite.xml` |
| `TEST_DATABASE_URL=postgresql+psycopg:///stocksense_codex_test uv run pytest --ignore=tests/e2e -q --junitxml=docs/evidence-postgres.xml` | 57 passed | `evidence-postgres.xml` |
| `uv run pytest tests/e2e -q --junitxml=docs/evidence-browser.xml` | 5 passed | `evidence-browser.xml` |
| `uv run pytest -q --junitxml=docs/evidence-mvp.xml` | 62 passed (57 service/HTTP/config + 5 browser) | Latest combined MVP verification |
| `uv run flask --app app db upgrade` on empty SQLite database | Passed | Initial migration applied; also exercised in each test fixture |
| `uv run flask --app app db check` | Passed: no new upgrade operations | Live local schema/model comparison |
| `uv run flask --app app reconcile` | Passed | All per-location balances match movement sums |
| `uv run python scripts/capture_screenshots.py` | Passed | Actual screenshots in `screenshots/`; no JavaScript page errors |
| `uv run python scripts/fresh_install_check.py` | Passed: fresh locked install, empty migration, seed, reconcile, two-worker Gunicorn health/login | Executed in an isolated temporary directory |
| Hosted GitHub Actions | Passed for initial published implementation (`e189fb5`): SQLite, PostgreSQL, browser, migration/seed/reconcile | https://github.com/Raajp10/stocksense/actions/runs/40745866259 |
| Render deployment and photo persistence after redeploy | Deferred beyond requested local prototype MVP | Prepared Blueprint retained |
| Physical camera on actual demo device | Not run | Requires Raaj's device/lighting/permission rehearsal |

## What the automated cases prove

- Exact 84/14/5-day example gives 22; ten approved incoming units reduce the suggestion to 12. Zero sales and zero completed days use threshold fallback without invented days remaining.
- Completed business-day windows exclude today's sale and include zero-sale days. New-product denominators and DST interval conversion are checked.
- Shelf sale, backroom transfer and delivery preserve the requested 8 → 6 → 6 → 30 arithmetic. Balance/ledger reconciliation is asserted.
- Same-token retries apply once; changed payload reuse is rejected. Two simultaneous sales or transfers cannot consume more than source stock.
- Injected failure during transfer or later order line rolls back all changes. Order receipt is accepted once. Approval recomputes other incoming stock.
- A changed stock version invalidates a count. Staff cannot approve corrections, edit prices/settings, approve/cancel orders or retrieve cost exports.
- Wrong-store IDs/QR codes cannot disclose or mutate objects. SQL composite foreign keys reinforce scope.
- Historical revenue retains price snapshots. CSV formula-leading text is neutralized. Invalid/oversized/high-pixel uploads are rejected; valid images normalize and survive application recreation with persistent paths.
- Browser workflows cover owner catalog/supplier/location/staff setup, photo upload, sale → transfer → order approval → receipt, staff denial, narrow layouts, manual fallback, and real jsQR decoding of a generated video stream.

## Defects observed and fixed

Initial model import used a mixin column name before class construction; relationship configuration was corrected before migration. Pytest import-path configuration was made explicit. Screenshot review found a silent chart initialization ordering bug; initialization now waits for DOMContentLoaded, and browser tests assert the chart exists. Expanded setup coverage found ambiguous select labels; accessible names were made explicit. All final evidence files must show passing results after these changes.

## Verification limits

Synthetic video exercises the real decoder and repeated frames, but cannot prove physical camera focus, classroom lighting or permission UX. Restart persistence proves local path durability, not a Render disk lifecycle. Local PostgreSQL tests do not certify a hosted service, backups or production TLS. Performance, penetration testing, physical camera rehearsal and actual classroom defense are not claimed.

The final local suite expands the initial hosted run with lifecycle, grouping, database-constraint, manual/QR parity and production-configuration cases. Inspect the latest main-branch Actions run for the expanded release suite.

MVP launcher: `./scripts/run_mvp.sh --check` prepares the configured local database, preserves existing records and verifies reconciliation. The user requested the prototype MVP in response to the hosting question, so paid hosting is outside the current handoff.
