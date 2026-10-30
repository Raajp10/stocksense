# Requirements and verification map

Source priority: Raaj's current instruction requests completing the work. The supplied conversation/specification defines StockSense behavior. The PDF supplies course deliverables; proposal slides supply the approved baseline. Document wording about earlier Phase 0 checkpoints is historical planning; the current instruction authorizes continuing through the implementation.

| ID | Requirement | Implementation | Evidence |
|---|---|---|---|
| FR01 | Owner/staff authentication and server roles | Flask-Login, Werkzeug hashes, owner decorator and service lock authorization | `test_staff_and_cross_store_boundaries`, CSRF test, browser staff test |
| FR02 | Catalog create/edit/archive | Product routes, validated cents and SKU, archive guards | Catalog HTTP and browser setup tests |
| FR03 | Supplier management | Owner settings, lead/safety days | Settings page render and browser supplier setup |
| FR04 | Atomic sale/delivery | Shared inventory execute service | Demo sequence, insufficient stock, concurrent sale, duplicate tests |
| FR05 | Owner-reviewed stock corrections | Count request/version and approval service | Stale count, fresh approval, staff denial |
| FR06 | Low and forecast-risk warnings | Reorder flags and dashboard | Arithmetic tests; UI render |
| FR07 | Explainable sales-based reorder | Completed local days, exact fractions, threshold floor and incoming deduction | 84/14 example; completed window; new product; zero sales |
| FR08 | Supplier order lists | Draft grouping, edit, approve, cancel, CSV, full receipt | Order lifecycle, stale recommendation, rollback, browser flow |
| FR09 | Dashboard | Cost valuation, revenue snapshots, units chart and rankings | Snapshot/DST/empty report test and actual screenshot |
| FR10 | CSV exports | Owner/store-scoped inventory, sales, reorder and order CSV | Export routes and formula-neutralization tests |
| FR11 | Executable handoff | uv lock, migration, seed, README, CI | Fresh setup rehearsal and public repository checks |
| FR12 | Photo and description | Separate validated upload; escaped bounded text | Invalid/oversized/pixel-limit tests, browser upload, restart persistence |
| FR13 | Stable QR and scan | Versioned token, qrcode, locally vendored jsQR, manual fallback, confirmation | Stable lookup test, synthetic video decoding, permission fallback |
| FR14 | Location balances/filtering | Location metadata, product/location search | HTTP listing, browser mobile checks, transaction assertions |
| FR15 | Atomic internal transfers | Transfer header plus opposite ledger entries | Concurrent and injected rollback tests; unchanged totals/reorder |
| FR16 | Shelf refill recommendations | Target gap limited by preferred source | Refill/transfer tests and browser workflow |

Nonfunctional requirements: local demo without external APIs/CDNs; keyboard-labelled forms; responsive layouts; CSRF on mutations; safe image handling; no negative stock; no cross-store references; installation from a fresh copy; documented limitations; truthful test/report evidence.

External delivery requirements remain distinct: public GitHub availability, successful hosted CI, Render deployment and durable-media redeployment check, physical-camera smoke test on the actual demonstration device, student understanding/defense, the December 9 classroom presentation and December 13 BrightSpace submission. These cannot be inferred merely from local passing tests.

## Current prototype MVP delivery scope

Raaj replied “make these proto MVP” to the paid-hosting question. The delivered scope is therefore the working local application and its reviewable source, tests, report and demo instructions. Hosting remains prepared future work. Physical-device rehearsal and scheduled course attendance/submission remain student obligations; none are represented as completed. Core functional requirements FR01–FR16 remain implemented.
