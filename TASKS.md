# StockSense task status

Current instruction: deliver the prototype MVP, following Raaj's reply “make these proto MVP” to the hosting question. The working local application, repository, tests and course report are the current deliverables; paid deployment is deferred. Requirements and evidence are tracked in docs/requirements.md and docs/release-checklist.md.

- [x] Phase 0: app factory, configuration, initial models, migration, dependency lock, health route, architecture/ERD and CI configuration.
- [x] Phase 1: authentication, server roles/store scoping, catalog, suppliers, photos/descriptions, stable QR labels, locations and staff settings.
- [x] Phase 2: atomic sale/receipt, location balances, ledger, transfers, count submission/approval, duplicate protection and concurrency/rollback checks.
- [x] Phase 3: completed-day reorder calculation, shelf refill suggestions, supplier drafts/edit/approve/cancel/receive and CSV export.
- [x] Phase 4 local application: dashboard, date-filtered chart, snapshots, CSV safety, responsive UI, owner/staff Playwright workflows and synthetic camera tests.
- [x] MVP local delivery: one-command launcher, private demo setup, migration, seed and reconciliation.
- Deferred beyond MVP: Render service and durable media redeployment checks.
- [x] Phase 5 preparation: PostgreSQL checks, report source, diagrams, screenshots, release docs and demo script.
- [x] Phase 5 local/public gates: fresh-install rehearsal, public repository with unauthenticated source access, 25-page generated PDF inspection.
- [x] Phase 5 initial hosted CI gate: run 40745866259 passed SQLite, PostgreSQL, browser, migration, seed and reconciliation. Expanded tests accompany the release update.
- [ ] Phase 6: physical-device camera and presentation rehearsal with Raaj.
- [ ] December 9: actual in-class demonstration and feedback.
- [ ] December 10–13: apply essential feedback, finalize submission, submit PDF/repository URL.

The remaining rehearsal and future course dates below are student follow-up obligations, not unfinished prototype implementation. Optional stretch features remain deferred. No AI API is needed to run the application. Do not mark hosting, physical camera, student understanding or scheduled submission complete without direct evidence.

## October 29 business workflow expansion

- [x] Whole-list document/email import, local OCR, supplier details and editable item matching.
- [x] Explicit order-draft versus delivery choices, atomic receipts and duplicate/reference checks.
- [x] Multi-product/location count sheets, assignment, blind count, saved progress, variance review and recount.
- [x] Visual categories/cards, direct actions, dashboard navigation and short-window sidebar fix.
- [x] Migrations preserve existing application data; core and new workflow tests run on SQLite/PostgreSQL and in a browser.
- [x] Refreshed 25-page report, screenshots, handoff, fresh installation and 95 passing local tests (84 service/configuration/HTTP + 11 browser).
- [ ] Final expanded-release hosted CI.
