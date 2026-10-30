# Verification evidence — expanded business MVP, October 29, 2026

Environment: macOS x86_64, CPython 3.12.14, locked Python dependencies, SQLite and PostgreSQL 14.18. Browser: Playwright 1.64.1 Chromium (plus an initial run through installed Chrome). Test databases and records are disposable and synthetic.

| Command / check | Actual result | Evidence |
|---|---|---|
| `uv run pytest --ignore=tests/e2e -q --junitxml=docs/evidence-sqlite.xml` | 84 passed | `evidence-sqlite.xml` |
| `TEST_DATABASE_URL=postgresql+psycopg:///stocksense_codex_test uv run pytest --ignore=tests/e2e -q --junitxml=docs/evidence-postgres.xml` | 84 passed | `evidence-postgres.xml` |
| `uv run pytest tests/e2e -q --junitxml=docs/evidence-browser.xml` | 11 passed | `evidence-browser.xml` |
| `TZ=UTC uv run pytest -q --junitxml=docs/evidence-mvp.xml` | 95 passed (84 service/HTTP/config + 11 browser) | Latest combined MVP verification |
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

Hosted UTC-boundary defect: the final MVP CI exposed tests constructing history with the runner's `date.today()` while production correctly used the store calendar. Test fixtures now use America/Chicago, and a fixed UTC-midnight regression verifies that a Chicago-today sale is excluded. The failed run was 40981165183; the correction is verified by the subsequent release run.

## Receipt / annual review expansion

The expanded local run passed 95 tests. Standalone SQLite and PostgreSQL runs passed 84 service/configuration/HTTP cases each, and Playwright passed 11 workflows. Real local Tesseract processed generated receipt photos and scanned PDFs; text PDF and HTML email extraction were also exercised. Tests cover editable supplier details, new/existing SKU matching, all-line receipt rollback/idempotency, duplicate references, order drafts with unchanged stock, owner purchasing reasons, multi-product/location sheets, blind counts, saved progress, stale sheet revisions, baseline refresh, recount history and atomic approval. Browser cases click actual row/location/count/recount/print actions and verify role restrictions, reachable sign-out/navigation and mobile layouts.

OCR results are suggestions, not universal receipt understanding. This historical run used Tesseract; the ML correction below supersedes that dependency. Original supplier PDFs/CSV and reviewed data are preferred. Private uploaded documents stay outside Git.

The button audit additionally verified owner-only restoration with stable QR tokens, blocked archival during active count sheets, and cancellation of an open request without stock changes.

Expanded business-workflow hosted CI passed for implementation commit `a3e8049`: https://github.com/Raajp10/stocksense/actions/runs/40989654598 . The job installed Tesseract and passed SQLite, PostgreSQL, all browser workflows, migrations, seeding and reconciliation.


## Actual invoice ML correction

The supplied fictional TEST-1042 image exposed a real failure missed by the earlier generated fixtures: supplier/reference columns were mixed, and a delivery label became an inventory row. The replacement bundles RapidOCR PP-OCRv4 ONNX CPU models and reconstructs fields/tables from positions. The exact image now yields Midwest Demo Supplies, TEST-1042, Oat Milk 1L × 12 at $3.50, Rice 1kg × 8 at $4.25, Black Beans 400g × 10 at $1.40, and $90.00. The fictional fixture is public; private uploads are excluded.

Regression checks include actual image recognition, resized/tilted variants, scanned/native PDF tables, money mismatch blocking, legacy finalization blocking, saved-source re-reading, replacement gating, explicit atomic/idempotent reversals and insufficient-stock rollback. Playwright verifies uploading the actual image, editing all rows, receiving and explicitly reversing the receipt. Local browser verification also confirmed the user's corrected draft #2 and unchanged movement count. The original wrong receipt was not silently reversed or re-received.

Final local verification: 98 SQLite service/HTTP tests and 12 Playwright workflows passed. The isolated 14-case ML/recovery suite also passed after the printed-line-total input validation change. Hosted PostgreSQL verification is recorded in the corresponding Actions run.


## Simple receiving for owners and workers

Local verification passed 103 service/HTTP cases and 15 Playwright workflows. Both owner and staff browser cases upload the actual TEST-1042 photo, verify the default destination, confirm delivery and add all three products without company or selling-price fields. Additional checks cover manual item controls, mobile layout, own-document restrictions, ignored privileged form fields, unchanged catalog prices, missing suppliers, mismatched totals, whole-list receipt safety, duplicate posts and blocked sales until new products are priced. Live draft #2 was checked at desktop and 390px width without receiving stock.
