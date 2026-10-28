StockSense — Codex implementation plan
Prepared for Raaj Patel • Software Design I • October 28, 2026

Revision 2: QR workflows, product images/descriptions, stock locations and shelf replenishment requested by Raaj before coding. These additions extend the approved proposal; they are not separately instructor-approved features.

1. Goal and source of requirements
Build an executable inventory and reorder assistant for a small business. Owners manage products and suppliers, review stock and sales, and prepare purchase orders. Staff record sales and deliveries. Reorder recommendations use recent recorded sales and an explainable formula.

This plan follows the approved 12-slide StockSense proposal and Course_Project_Submission_Guidelines.pdf supplied by Raaj. The instructor's approval confirms the proposal, not implementation results. All tasks below are planned work; no application, test results, repository, or deployment has been created or verified in this planning task.

Course obligations:

In-class demonstration: Wednesday, December 9, 2026, CLO 363. Check BrightSpace for the announced time and additional instructions.
Final submission: December 13, 2026, 11:59 p.m. Confirm the LMS timezone; the PDF does not specify one.
Executable application and public GitHub repository accessible without permission.
Root README with problem, features, technologies, prerequisites, installation, execution, safe sample account details, and UI screenshots or description.
Technical report of at least 20 pages, with the required six chapters, at least two explained design diagrams, a test-results table, screenshots, and consistent references.
AI assistance is permitted, but Raaj must understand and defend the code. Record significant assistance and follow applicable disclosure requirements.
2. Scope contract
Required application scope
ID	Capability	Completion criterion
FR01	Owner and staff authentication	Hashed passwords, logout, authenticated routes, server-side role enforcement
FR02	Product catalog	Owner creates/edits/archives products with SKU, category, cost, selling price, supplier, reorder level
FR03	Supplier management	Owner maintains supplier name, contact details, lead time and safety days
FR04	Sales and deliveries	Staff and owner record quantities; inventory and movement history update atomically
FR05	Inventory corrections	Staff submit a physical count and reason; owner approves the stock adjustment
FR06	Stock warnings	Show items at/below reorder level and items projected to run out within lead time plus safety days
FR07	Reorder recommendations	Show inputs, 14-day sales average, formula, and suggested quantity for each product
FR08	Supplier order lists	Owner creates drafts grouped by supplier, edits quantities, approves, exports CSV, and records receipt
FR09	Dashboard	Show stock value at cost, low-stock count, fastest/slowest sellers, and sales chart
FR10	CSV exports	Owner exports inventory, sales, and reorder/order lists with clear columns and date ranges
FR12	Product photos and descriptions	Owner adds one optional validated photo and a description; scanner confirmation shows them
FR13	Product QR labels and scanning	Print labels; scan to look up a product for sale or receipt; confirmation required before stock changes
FR14	Stock locations	Track quantity by named location within one store; filter/search by aisle, shelf or bin
FR15	Internal stock transfers	Move units between locations atomically, with an audit trail and unchanged total stock
FR16	Shelf refill list	Show shelves below target and suggest available backroom stock to move; separate from supplier reorder
FR11	Executable delivery	Fresh clone can be installed, migrated, seeded, tested, and launched using the README
Proposed boundaries to keep the project achievable
One store per account; no public registration, billing, or subscription system. Store-scoped data from the beginning; use two stores in isolation tests.
Whole-number inventory units: bottles, bags, boxes, cups. Define the unit per product. Fractional weights and unit conversion are future work.
A sale records product and quantity; StockSense is not a payment processor or full checkout system.
Owner manages staff accounts. Staff cannot change product cost, price, supplier settings, or purchase-order approval.
No lot tracking, expiration-date automation, recipes, dedicated barcode hardware integration, or supplier API integration in the required release. State these limitations honestly for café use.
QR identifies a product type/SKU, not an individually serialized physical item. Each sale requires a selected quantity and source location. Existing manufacturer barcode recognition is a future enhancement.
Locations are shelves/bins within one store, not separate warehouses or branches.
Full purchase-order receipt only in the first release. Partial delivery support is optional and must not be implied by the UI.
CSV is the required order export. Printable/PDF orders are secondary. Supplier email and Gemini assistant remain stretch goals.
A deployed Render instance is the proposal target; a documented local run remains essential for classroom reliability.
3. Technology and architecture
Retain the approved choices: Python 3.12, Flask, Jinja2, Bootstrap 5, Chart.js, SQLAlchemy, SQLite for local development, PostgreSQL for hosting, Flask-Login, Werkzeug password hashing, pytest, Playwright, GitHub Actions, and Render. Add Flask-WTF for CSRF/form handling and Flask-Migrate/Alembic for database migrations as implementation choices.

These are planning choices from the proposal, not claims about current package versions or free hosting availability. At setup, verify compatible supported versions against official documentation and lock dependencies. Verify Render pricing, persistence, build/start commands, and CI deployment gating before configuring hosting. Do the same for Gemini quotas/model availability only if the stretch goal is reached. No paid service is required for the local application.

Use one Flask application with an application factory and blueprints. Avoid a separate React app, microservices, or a generic repository framework. Keep routes thin: authentication and form parsing in routes; business rules in services; persistence in SQLAlchemy models; presentation in templates.

Suggested modules:

app/__init__.py, config.py, extensions.py: app creation and environment-specific configuration.
app/models/: store, user, supplier, product, location, stock balance, transfer, sale, stock movement, order, count request.
app/auth/, catalog/, inventory/, orders/, dashboard/, exports/: blueprints, forms, and routes.
app/services/inventory.py: transactional sale, receipt, and adjustment operations.
app/services/scan.py: parse allowlisted QR payloads and resolve products within the current store; no inventory writes.
app/services/media.py: validate, normalize and persist product images.
app/services/transfers.py: location transfers and shelf-refill suggestions.
app/services/reorder.py: pure calculation plus query orchestration.
app/services/orders.py: draft creation, approval, receipt, cancellation.
app/services/reporting.py: date-scoped, store-scoped aggregates.
app/templates/, app/static/: shared layout, pages, locally available demo assets.
migrations/, tests/unit/, tests/integration/, tests/e2e/, docs/, .github/workflows/.
Root files: README.md, .env.example, .gitignore, dependency lock, PLAN.md and TASKS.md.
Architecture documentation must show browser → Flask routes → services → database, with the optional AI tool adapter clearly separate. A second diagram should show database relationships. A stock-sale sequence diagram is useful additional evidence.

4. Data design and invariants
Entity	Important fields and constraints
Store	ID, name, business timezone
User	ID, store ID, unique login/email, password hash, role, active flag
Supplier	ID, store ID, name, contact, lead time days, safety days, archived flag
Product	ID, store ID, supplier ID, SKU unique within store, name, description, image storage key, stable unique QR token, category, unit, cost cents, price cents, reorder level, created timestamp, archived flag
Location	ID, store ID, unique code within store, name, area/aisle/shelf/bin labels, type (sales shelf/backroom/general), archived flag
StockBalance	ID, store ID, product ID, location ID, nonnegative quantity, version; unique product/location pair
ShelfRule	ID, store ID, product ID, shelf location ID, preferred source location ID, target quantity; unique product/shelf pair
StockTransfer	ID, store ID, product ID, source/destination location IDs, positive quantity, actor, timestamp, unique operation token
Sale	ID, store ID, product ID, source location ID, positive quantity, price snapshot cents, recorded-by user, effective timestamp, unique submission token
StockMovement	ID, store ID, product ID, location ID, signed quantity delta, type, actor, reason, timestamp, reference to sale/order receipt/count approval/transfer
PurchaseOrder	ID, store ID, supplier ID, status, created/approved/received timestamps, actor references
PurchaseOrderItem	ID, order ID, product ID, receipt destination location ID, positive quantity, unit-cost snapshot cents; one product per order
StockCountRequest	ID, store ID, product ID, location ID, counted quantity, reason, observed stock version, requester, approver, status
StockBalance is the authoritative cached balance per product/location, maintained in the same transaction as the movement ledger. Product stock on hand is computed as the sum of its StockBalance quantities; do not maintain a second mutable product-level quantity. Opening balances also create location-specific movements. Require StockBalance.quantity >= 0, nonnegative money values, valid roles/statuses, and store-consistent references. Use integer cents for money; do not calculate monetary totals with binary floats. Historical sale/order values use their snapshots even after catalog prices change.

Archive referenced products and suppliers rather than deleting history. Archived products remain visible in historical reports but cannot receive new sales or orders. Keep foreign keys enabled in SQLite. Validate related records against the signed-in user's store; never trust a submitted store ID.

For sales, atomically decrement the selected location balance only where stock is sufficient, check the affected row, then insert the sale and movement in the same transaction. Roll back all writes on failure. For receipt, atomically claim the approved order transition and add its movements once. Unique operation tokens/reference constraints must prevent duplicate submissions from duplicating sales or stock. Test the behavior on PostgreSQL as well as SQLite.

For counts, if stock at the counted location changed since the count was submitted, require a fresh count rather than applying a stale absolute quantity. Owner approval writes the signed adjustment and balance together. Historical stock movements are append-only; corrections use explicit compensating movements with reasons.

5. Business rules to implement exactly
Sales window and reorder calculation
Throughout these calculations, stock_on_hand means the sum across all locations for that product in the current store. Internal transfers, receipts, count adjustments and opening balances are not sales and must never enter the sales average. Shelf replenishment uses a separate rule in Section 14.

Use the previous 14 completed business-calendar days, excluding today's incomplete day. Include zero-sale days. For a product created during that window, divide by the number of completed days since creation, capped at 14. With no completed days, display “insufficient history” and use the manual reorder threshold fallback.

For established products:

average_daily_sales = units sold in window / 14
coverage_days = supplier.lead_time_days + supplier.safety_days
forecast_target = ceil(average_daily_sales * coverage_days)
target_stock = max(product.reorder_level, forecast_target)
base_suggestion = max(0, target_stock - stock_on_hand)
actionable_suggestion = max(0, target_stock - stock_on_hand - approved_unreceived_units)
days_remaining = stock_on_hand / average_daily_sales, if average_daily_sales > 0
The proposal example must pass: 84 units sold in 14 days, lead time 3, safety days 2, stock 8, no open order, and reorder level at most 30 gives average 6/day, target 30, and reorder 22.

The manual threshold floor and deduction of open orders are proposed implementation refinements. Display both the forecast calculation and any threshold adjustment so the result stays explainable. Draft orders do not reserve stock. Recompute/review recommendations when approving drafts to avoid duplicate purchasing.

An item is low when stock_on_hand <= reorder_level. It is at forecast risk when average sales is positive and days remaining is at most coverage days. If sales are zero, show “No recent sales” and no numeric days-remaining estimate. At the threshold, the suggested order can be zero; label this honestly rather than forcing a positive order.

Recorded sales underestimate demand during stockouts. Document that limitation. Do not claim learned forecasts, seasonal modeling, or proven waste reduction.

Orders and reports
Order lifecycle: draft → approved → received; draft/approved → cancelled. Received/cancelled orders cannot be received. Editing is allowed only for drafts. Stock changes only on receipt, never on draft or approval. Staff can receive approved orders; owners approve and cancel them.

Use product units sold for fastest/slowest sellers, include active zero-sale products in slowest sellers, and show the reporting dates. Stock value means current quantity × current cost. Sales revenue uses sale-price snapshots and is not profit. Convert local calendar filters to UTC bounds consistently.

CSV exports must escape quotes/newlines correctly and neutralize formula-leading text in user-entered fields. Show cost-based exports only to owners. Keep exports scoped to the current store.

6. UI and permissions
Pages: scan action selection; QR label print view; locations and balances; transfer form; shelf refill list; login; dashboard; searchable products; product detail and movement history; supplier list/edit; record sale; receive delivery/order; pending stock counts; low-stock/reorder list; supplier order detail; reports/exports; owner staff settings.

Use a consistent navigation, clear units and dates, labelled forms, keyboard-accessible controls, readable empty states, and validation that preserves inputs. Validate narrow phone layouts as well as desktop. Show loading/submission state, success feedback, insufficient-stock errors, and duplicate-operation handling. Refresh inventory after successful writes; “live” means current database values on page load/refresh, not promised WebSocket streaming.

Action	Owner	Staff
View stock and warnings	Yes	Yes
Record sales and deliveries	Yes	Yes
Scan products and transfer stock between locations	Yes	Yes
Manage photos, locations and shelf targets	Yes	No
Submit count request	Yes	Yes
Approve stock correction	Yes	No
Edit catalog/prices/settings	Yes	No
Approve/cancel orders	Yes	No
View cost analytics/export accounting data	Yes	No
Manage staff accounts	Yes	No
All permissions must be enforced in server handlers and services, not only by hiding buttons. Require CSRF protection for mutations, safe session settings in production, generic login failure messages, and secrets through environment configuration. Use fictional demo data. Do not publish production credentials or enable a development debugger on hosting.

7. Codex implementation milestones
Each milestone ends with working code, relevant checks, updated documentation, and a short explanation Raaj can defend. Do not treat generated code as verified until commands actually run successfully.

Phase	Target dates	Codex work	Exit evidence
0 — Design and scaffold	Oct 28–Nov 1	Record scope, ERD, app factory, configuration, dependency lock, migrations, initial CI	App starts; empty DB migrates; health check and configuration test pass
1 — Auth and catalog	Nov 2–8	Owner/staff login, access checks, stores, suppliers, products with photo/description/QR, locations, staff management, seed command	Role denial and cross-store tests pass; catalog workflow works
2 — Inventory transactions	Nov 9–15	Sales/receipts through manual and QR entry, location balances, transfers, stock ledger, count approval, duplicate protection	No negative stock; duplicate/concurrent actions handled; history reconciles
3 — Reorder and purchasing	Nov 16–22	Reorder calculation, shelf refill list, alerts, draft/approve/receive/cancel flow, supplier CSV	Oat-milk example gives 22; receipt happens once; open orders reduce suggestion
4 — Dashboard and full workflow	Nov 23–29	Aggregates, charts, exports, responsive UI, Playwright flows, staging hosting	Owner/staff and camera workflows pass; report totals match fixtures; DB and uploaded photos persist
5 — Release and report	Nov 30–Dec 6	PostgreSQL checks, fresh-clone rehearsal, defects, screenshots, report, demo script	Core scope frozen; clean installation works; report first complete draft
6 — Demo rehearsal	Dec 7–8	Rehearse demo, reset data, prepare local backup and version tag	Demo completes within allotted time on intended machine
In-class demo	Dec 9	Demonstrate app and explain code	Record genuine feedback and issues
Final submission	Dec 10–13	Address essential defects, reconcile docs/tests, finish PDF and URLs	Public repository, executable instructions and >=20-page PDF verified
AI is eligible only after Phase 4 exits and only if it does not threaten release preparation. If behind schedule, cut AI, PDF export, email, and optional charts first. Preserve correctness, executable setup, tests, and report.

8. Test plan and evidence
Create deterministic synthetic data: one café with three suppliers and 15–20 products, 30 days of sales, a low-stock product, a zero-sale product, a newly created product, and approved/draft orders. Include Shelf A-02 and Backroom B-04, fixture photos and printable QR labels. Generate data through the same domain operations or provide reconciliation checks. Add a second store for access tests. Allow a fixed reference date for calculation tests.

Test	Expected result
84 units / 14 days; stock 8; coverage 5	22-unit base reorder
Zero-sale days in the 14-day window	Denominator still 14 for established products
Newly created product	Uses completed available days; no division by zero
No sales / stock below threshold	Manual-threshold fallback; no invented days-remaining
Approved open order for 10 of the 22 units	Actionable suggestion becomes 12
Sale of 9 when stock is 8	Rejected; stock and ledger unchanged
Duplicate sale submission	Exactly one sale and stock decrement
Two competing sales for last unit	One succeeds; other fails; stock never negative
Receive same order twice	Exactly one receipt and stock increment
Failure midway through receipt	Entire transaction rolls back
Staff sends direct price-edit request	Denied; price unchanged
User guesses another store's product/order/export ID	No data disclosure or mutation
Stale physical count approval	Rejected; new count requested
Product price changes after sale	Historical sales total unchanged
CSV text starts with a formula character	Spreadsheet formula execution neutralized
Month/date boundary and empty report	Correct interval and readable empty state
Unit tests cover arithmetic and state transitions; integration tests cover transactions, authorization, filtering and exports. Playwright covers owner setup → sale → warning → order → receipt, and staff denial paths. PostgreSQL integration is necessary before claiming deployment compatibility. Capture actual test commands, date, environment and results in docs/test-results.md; mark unrun cases “Not run.” Screenshots must come from the working application.

CI should install locked dependencies, run unit/integration checks, and run required browser flows. Configure deploy only after required checks pass; merely enabling independent auto-deploy is not sufficient. Record failures and fixes. Avoid making arbitrary coverage percentages the main measure of correctness.

9. Report and course grading alignment
Graded component	Weight	Evidence to prepare
Public GitHub	5%	Repository URL checked while signed out
README	5%	Fresh-clone setup and run instructions exercised
Executable demo	20%	Working end-to-end app and local fallback
Introduction	5%	Problem, motivation, benefits framed as goals
Requirements	5%	Functional/nonfunctional requirements, users, assumptions
Design	15%	Architecture and ER diagrams with captions; design tradeoffs
Implementation	25%	Explain major features and implementation decisions
Testing/results	15%	Actual results table, screenshots, defects and fixes
Conclusion	5%	Achievements, limitations, realistic future work
Target 23–25 pages to leave room for readable diagrams. Suggested allocation: title/contents 2; Chapter 1 2; Chapter 2 3; Chapter 3 4; Chapter 4 5; Chapter 5 4; Chapter 6 1; references 1–2. The requirement is at least 20 pages, not this exact allocation. Use IEEE references consistently. Avoid filling pages with source listings. Draft requirements/design early, then update implementation and results to reflect what actually shipped.

Maintain docs/decisions.md, docs/requirements.md, docs/test-results.md, docs/demo-script.md, docs/ai-usage.md, and screenshot assets during development. Record why Flask, a service layer, transactions, store scoping, and deterministic reorder arithmetic were chosen. Do not write measured business improvements without real evidence.

10. Classroom demo plan
Prepare a roughly 5–7 minute version, then adjust to the instructor's announced limit:

Explain the shop problem and show a product photo, description and QR label.
Show location balances: oat milk has 3 on Shelf A-02 and 5 in Backroom B-04, total 8.
Scan its QR in Sell mode, confirm 2 units from the shelf: shelf 1, backroom 5, total 6.
Open the shelf refill list and transfer 4 from backroom: shelf 5, backroom 1, total still 6.
Show average sales 6/day over the previous 14 completed days and coverage 5 days: target 30; supplier reorder 24. Today's demo sale does not change that historical average.
Approve an order for 24. Scan to identify its line, confirm complete receipt to backroom: shelf 5, backroom 25, total 30. Attempting receipt again must leave 30.
Show staff restrictions and the movement history for each action.
Explain the service-layer calculation, tests, and a limitation. Keep the original 8-stock/22-unit reorder case as a separate deterministic test.
Keep a local database and dependencies ready. Core demo must work without an AI API or external CDN. Do not depend on a hosting cold start or classroom network. Rehearse explaining or modifying the reorder formula, a permission check, and a transaction.

11. Copy-paste kickoff prompt for Codex
Build StockSense for my Software Design I course using the attached
StockSense_Codex_Plan.md as the implementation specification.

Read this plan and any existing repository instructions first. Inspect the
repository before making changes. Preserve existing user work. If no repository
exists, scaffold a local project. This task starts with Phase 0 only.

Retain Python 3.12, Flask/Jinja2, Bootstrap 5, Chart.js, SQLAlchemy,
SQLite locally, PostgreSQL for deployment, Flask-Login, Werkzeug hashing,
pytest, Playwright, GitHub Actions, and a Render deployment target.
Verify compatible dependencies using official documentation and lock them.

Create the app factory, configuration, extensions, blueprints, initial models,
migrations, dependency files, README, .env.example, .gitignore, and basic CI.
Copy the plan to PLAN.md and create TASKS.md with phase checklists. Document
the architecture and ER model. Implement a health route and a deterministic
development seed command with fictional data and environment-supplied passwords.

Use thin routes and service-layer business logic. Enforce store scoping,
server-side roles, CSRF protection, integer cents for money, and whole-number
stock units. Design inventory operations for atomic updates and duplicate
submission protection. Include location balances as the source of inventory truth;
compute product totals from them. Include product descriptions, image keys and
stable QR tokens in the initial schema. Read Section 14 before designing models.
QR and manual input must call identical inventory services. Do not mutate stock
on scan recognition. Never commit secrets or real business data.

Run the checks appropriate to Phase 0, including migration from an empty
database and app startup. Report exact commands, results and anything blocked.
Do not claim a check passed if it was not run. Explain the key files and design
decisions so I can defend them in class. Update TASKS.md and stop at the Phase 0
checkpoint with the next task ready. Do not add AI or expand scope.
12. Reusable prompt for later phases
Read PLAN.md, TASKS.md, and repository instructions. Complete the next unfinished
phase and its acceptance criteria. Inspect the existing implementation first.
Keep the approved stack and scope. Add meaningful tests for new business rules,
permissions and failure cases. Run relevant checks, update docs and TASKS.md,
and report what changed, evidence that it works, remaining issues, and what I
should understand for the demonstration. Do not fabricate screenshots, test
results, deployment status, or completed requirements.
13. Final definition of done
Every core requirement has implemented behavior and traceable verification.
Stock balances reconcile with location movements; product totals equal summed balances. Transfers preserve total stock. QR/manual flows produce identical results; role and store boundaries hold.
Product images survive the documented hosting lifecycle, labels remain valid after product edits, and the scanner has a working manual fallback.
Clean installation and migration work using the committed README.
No secrets or real customer data are in the public repository.
PostgreSQL/deployment behavior is verified before being described as supported.
The December 9 demo can run locally with realistic synthetic data.
The report has at least 20 pages, all required chapters, explained diagrams, actual test results, screenshots and references.
The public repository link works while signed out and is in the report/BrightSpace submission.
Raaj can explain the reorder formula, data model, transactions, permissions, test strategy and limitations.
14. Detailed design for QR, product information and locations
14.1 Product creation and QR labels
Owner enters name, SKU, description, unit, price/cost, supplier and reorder settings; adds an optional photo; and optionally enters opening quantity at a selected location. Saving catalog details with zero opening quantity must not create stock. A nonzero opening quantity creates one opening-balance movement through the inventory service. Subsequent catalog edits must never reset stock.

Generate a stable random product token and encode a versioned payload such as stocksense:v1:product:<token>. The code identifies a product, not a quantity, price, user credential or permission. Editing names, prices, descriptions or photos must not invalidate existing labels. Server lookup must also enforce the signed-in store and active-product status. Unknown/wrong-store codes give a generic not-found result. Never auto-open arbitrary scanned URLs or execute embedded commands.

Provide a print-friendly label with QR, product name, SKU and unit. Use one code per product type for the class demo. A pack and an individual unit need distinct SKUs if both are stocked independently; scanning a box does not silently convert it into individual units.

Choose a maintained QR generator/decoder at implementation time, verify official documentation/license and lock versions. Serve decoder assets locally for the classroom fallback. Do not assume all browsers have the same built-in decoding API. Supplier/manufacturer UPC/EAN scanning and automatic internet product lookup are future work, not required for these custom labels.

14.2 Scan workflow
User selects Sell, Receive, Transfer or Lookup. Display the mode prominently.
User scans the code or types the SKU/code in the fallback input.
Resolve product and show name, photo, description, unit and current location quantities.
Ask for positive whole-number quantity and location. Sale uses a source; receipt uses a destination; transfer uses both.
Show the intended action and projected quantity, then require explicit confirmation.
Submit one operation token to the server, recheck role, store and actual current stock, commit atomically, and show actual saved balances.
Pause scanning after the first recognized code until the user completes/cancels the action. Repeated camera frames must not increase quantity or post additional transactions. Frontend button disabling improves usability; backend idempotency guarantees correctness after double clicks, retries and network ambiguity. Reuse the same token for retrying the same operation and reject reuse with different payloads. Never show success until a server-confirmed result is available.

Scanning an unknown code allows only owners to choose a separate Add product flow; it must not create a product or alter stock automatically. A photo is for human identification, not image recognition or proof of identity.

For an approved purchase order, scanning identifies/checks a line. It must not create a second standalone receipt. The first release confirms the complete order once, with a destination for every line; scanned lines are only a review aid. For standalone deliveries, record a supplier/reference and reject duplicate operation tokens. Document that matching physical deliveries entered as unrelated new operations cannot always be detected automatically.

14.3 Product photos and descriptions
Store one optional photo per product and show a neutral placeholder when absent. Use a description length limit (for example 1,000 characters), escaped text, and owner-only editing. Staff may view details during scanning.

Proposed image policy: JPEG/PNG/WebP input, maximum upload 5 MB and decoded pixel limit, actual image decoding to validate contents, normalization to a bounded display size, metadata stripping, and random server-generated storage keys. Do not accept SVG/HTML or rely on filename extensions. Avoid arbitrary remote image URLs. Treat image uploads as separate from stock operations; a failed photo upload must not change stock. Delete replaced files only after the database update succeeds.

Use a configured upload directory for local runs. Before hosting, choose and document persistent media storage suitable for the selected hosting plan; do not write user uploads only to a disposable application filesystem. Ship small licensed or original demo fixture images with attribution where needed, but keep arbitrary user uploads outside Git. Test product photos after a service restart/redeploy.

14.4 Locations, transfers and shelf replenishment
Locations represent physical positions inside one store, such as Shelf A-02, Fridge F-01 and Backroom B-04. Allow a product in several locations and several products in one location. Show quantity at each and the total. Owners manage locations and shelf targets. Prevent archiving a location with stock or pending operations; move/resolve them first.

All transactions carry locations. A sale cannot borrow silently from backroom when the selected shelf is empty. Offer an explicit transfer or selection of the correct physical source. Stock counts apply to one location. Receipt destinations must belong to the same store. Location IDs from another store are rejected.

A transfer creates one header and two linked ledger entries in the same transaction: negative at source, positive at destination. Both sides use the same product and quantity. Check source != destination, positive quantity, sufficient source stock, active locations and store consistency. Lock/update balances in consistent order and retry only safely on database concurrency errors. Rollback must leave both balances unchanged. A repeated token applies the transfer once. A transfer changes neither total stock, sales revenue, sales averages nor supplier reorder quantity.

For one owner-configured shelf rule:

shelf_gap = max(0, shelf_target - shelf_quantity)
refill_suggestion = min(shelf_gap, preferred_backroom_quantity)
remaining_gap = shelf_gap - refill_suggestion
Display source, destination, available source stock and suggested move. A list suggestion is advisory, not a reservation; confirm against current balances when executing it. Avoid presenting aggregated suggestions as guaranteed stock if several shelves share a source.

Keep two separate dashboard actions:

Refill shelf: move existing units from backroom to shelf.
Order from supplier: buy more units based on total stock and approved incoming orders.
An empty shelf with ample backroom stock should be prominent on the refill list without being called a store-wide stockout. Do not automatically convert a remaining shelf gap into a purchase order, because the store-level reorder rule is the purchasing authority.

14.5 Extra ideas ranked by value
Include these small additions with the requested workflows: printable QR labels, location filters, a recent-activity feed from existing stock movements, and clear before/after quantities on confirmation screens. Shelf refill recommendations are included because they make locations actionable.

Defer these until the required release is stable: supplier barcode mapping, bulk CSV product import with preview/validation, low-stock email digests, batch/expiry tracking, customer returns, and Gemini Q&A. Returns require explicit revenue and inventory reversal rules; do not add a generic Undo button that silently rewrites history. Damaged/expired stock can initially be recorded through the existing owner-approved adjustment with a reason, without claiming full expiry management.

14.6 Additional acceptance checks
Scenario	Expected result
Create product with photo/description and opening stock	One catalog record, valid image, stable QR, one opening movement if quantity is positive
Edit catalog/photo after sales	Quantity and historical movements unchanged; old printed code still resolves
Scan one label continuously	One confirmation screen; zero writes until confirmation
Submit same sale via retry	Exactly one deduction and one sale
Manual vs QR sale from identical starting state	Identical saved quantity, revenue and movement data except input-channel metadata
Sell 2 from shelf 3/backroom 5	Shelf 1, backroom 5, total 6
Transfer 4 from that backroom to shelf	Shelf 5, backroom 1, total 6; reorder and sales metrics unchanged
Receive approved 24-unit order to backroom	Shelf 5, backroom 25, total 30; repeated receipt leaves total 30
Insufficient selected-location quantity	Rejected even if another location holds stock
Two simultaneous transfers from the same source	No negative source, duplicate movements or lost units
Failure during transfer	Neither side commits; total and both location balances unchanged
Count approval after that location changed	Reject stale count and request recount
Unknown/malformed/other-store QR	No stock mutation and no cross-store data disclosure
Invalid/oversized/decompression-heavy image	Clear validation failure; no executable upload or stock side effect
Camera permission denied or unavailable	Manual SKU/code entry remains usable
Image reload after restart/redeploy	Photo remains available with documented media persistence
Test parsing and business services automatically; test scanner callbacks with decoded fixture payloads in browser tests. Separately perform a real-camera smoke test on the intended demo device, including lighting, focus and permission denial. Do not claim actual camera capture was tested merely because a callback was mocked.

14.7 Camera demo environment
Browser camera capture requires user permission and a secure context. HTTPS is the hosted target; localhost is suitable for development on the same machine. A phone opening a laptop's plain-HTTP LAN address is not equivalent to localhost. Verify the intended phone/browser arrangement before the demonstration. Use laptop localhost/webcam or an HTTPS deployment, with manual SKU entry as fallback. Stop video tracks when leaving the scanner. This application does not need microphone permission or server upload of camera frames.

Reference checked October 28, 2026: MDN, MediaDevices.getUserMedia(), https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia . Recheck scanner dependency/browser compatibility during implementation.

Source references
Raaj Patel, Project_Proposal_Proposal_Raaj_Patel (1).pptx, 12 slides. Approved StockSense scope, stack, architecture, formula and stretch goals.

Course_Project_Submission_Guidelines.pdf, 3 pages. Course deliverables, dates, report structure, grading and responsible tool use.

User-provided instructor feedback: “Your project proposal titled 'StockSense' has been approved.”

Raaj’s October 28 follow-up: QR-based add/sell workflows, product pictures/descriptions, location tracking, consistent calculations, and useful additional features.

