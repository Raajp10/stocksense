# StockSense prototype MVP

Raaj requested a prototype MVP in response to the paid-hosting question. The local demo is the current delivery. Core functionality from the plan is preserved; a hosting subscription is unnecessary to evaluate it.

## Start

From the project directory, run `./scripts/run_mvp.sh`, then open http://127.0.0.1:5050. The first run prepares dependencies and an empty database; later runs retain existing records. Demo accounts are `owner@stocksense.test` and `staff@stocksense.test`. Their private passwords are in `.env`. Sign out before switching roles.

The launcher uses localhost, which supports camera access on that same machine. A phone needs a verified HTTPS arrangement; manual SKU entry works on the laptop without camera permission.

## MVP demonstration

1. Open Products → Oat milk. Review photo, description, printed QR label and quantities by location.
2. Choose Scan & record → Sell. Scan the label or enter `OAT-001`. Choose quantity and source, review before/after and confirm.
3. Open Refill shelves and review a backroom-to-shelf transfer. Total stock stays unchanged.
4. Open Reorder assistant, expand the calculation, select a product and create a supplier draft. Approve, check every delivery line and receive the complete order once.
5. Inspect movement history. Sign in as staff to demonstrate restricted settings and owner exports.

The deterministic scenario is covered by tests: starting shelf 3/backroom 5, sell 2 → 1/5, transfer 4 → 5/1, receive 24 → 5/25. The complete rehearsed narrative is in `demo-script.md`. Use a fresh separately seeded demo on the presentation day to keep historical sales aligned to that business date.

## Included artifacts

- Runnable Flask application and local SQLite database setup.
- Stable QR labels, camera/manual input, images and location-based stock arithmetic.
- Owner/staff roles, catalog/settings, physical counts, purchasing, reports and safe CSV exports.
- Locked dependencies, migration, fictional seed, automated tests and public GitHub source.
- A 25-page course report with six chapters, diagrams, screenshots and actual test results.

## Follow-up

Render hosting and hosted-media redeployment testing are deferred beyond the MVP. Physical-camera optics on the classroom device still require Raaj's rehearsal. The December demonstration and final BrightSpace submission remain scheduled course obligations. AI Q&A, email and other optional features remain future work.

## New business workflows

Use **Receive & import** for a whole receipt or supplier email. Text PDFs and CSV are preferred; photos/scanned PDFs use bundled local RapidOCR PP-OCRv4 / ONNX CPU models. Spatial reconstruction keeps table columns together, and exact money checks block inconsistent receipts. Check item names, quantities and unit costs, confirm one receiving location, then add all items. Supplier details are saved automatically; owners can open More options for the full review or a purchase order. The source and finalized review remain traceable.

Use **Stock reviews** for an annual or cycle count across multiple products and locations. Owners request the sheet, staff save/submit manual observations, and owners review differences before approving or asking for a recount. Category cards, stock filters, sorting and a compact table are available under Products. The sidebar scrolls on short screens so sign-out and settings remain reachable. Owners can restore archived records and cancel an unneeded count request without changing stock.

Simple bill receiving is the default for both roles: upload, check products/quantities/unit costs, confirm one receiving location and add all items. Supplier/contact fields and catalog setup are handled in the background; owners retain the optional full review. New products can be stocked before pricing; sales require a positive owner-set price. Workers may receive their own documents but cannot reverse receipts, change existing catalog prices, update supplier contacts or manage purchase orders.
