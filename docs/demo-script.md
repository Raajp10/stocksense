# StockSense classroom demonstration (5–7 minutes)

Use a newly seeded demo database on the actual demonstration day so the 14-day history stays current. Do not reset a database containing valuable data. Back up SQLite and media together, then create a separate database with `DATABASE_URL=sqlite:////absolute/path/demo.db` and a separate `UPLOAD_DIR` if needed. Migrate, seed and reconcile using the README. Seed refuses to overwrite an existing store.

1. **Problem and catalog, 45 seconds.** Sign in as owner. Explain the café's inventory visibility problem. Open Oat milk, show original fixture photo, description, SKU, unit and printable QR label. Explain that one code identifies a product type.
2. **Starting positions, 30 seconds.** Show Shelf A-02 = 3, Backroom B-04 = 5, total 8. On Reorder assistant the previous 14 completed days contain 84 units sold: average 6/day, coverage 3+2=5, target 30, suggestion 22. Expand the explanation.
3. **Sale, 45 seconds.** Scan Oat milk in Sell mode or enter `OAT-001`. Select quantity 2 and source A-02. Review before/after. Confirm. Shelf becomes 1, backroom remains 5, total 6. Today's sale is excluded from the completed-day average.
4. **Refill, 45 seconds.** Open Refill shelves. Its target is 5; gap is 4 and backroom has 5. Review and confirm the 4-unit transfer. Shelf becomes 5, backroom 1, total remains 6. The supplier suggestion stays 24; the transfer is not a sale.
5. **Supplier order, 60 seconds.** On Reorder assistant select only Oat milk (uncheck other suggestions). Choose B-04 as destination and create draft. Inspect quantity 24 and cost snapshot. Approve. Approved incoming units reduce the remaining suggestion to zero. Optionally scan-check the line from the order page. Check all units/destination, then receive the complete order. Shelf becomes 5, backroom 25, total 30. Received status removes the receipt action. Retry the same submission in automated tests, rather than entering a new delivery.
6. **Account boundaries and history, 45 seconds.** Sign out and sign in as staff. Show that catalog editing, price settings, owner exports and order approval are unavailable; direct server requests are tested too. Show movement history with actor and location.
7. **Defense, 45 seconds.** Explain `app/services/inventory.py` and `app/services/reorder.py`. Mention exact cents, the operation token, store lock and rollback. Explain that sales underestimate demand during stockouts and partial receipts/expiry tracking are outside scope.

## Device rehearsal requiring Raaj

Print the label before class. Use localhost on the laptop's own webcam, or a verified HTTPS host for a phone. A phone opening a laptop's plain HTTP LAN URL is not localhost. Grant camera access, try typical room lighting/focus, deny access once and demonstrate manual fallback, stop scanning and verify the camera stops. Confirm physical scan results without claiming success from a synthetic stream. Prepare a local copy, installed dependencies, saved credentials and manual SKU fallback.

## Study questions

- Why does transferring 4 units leave total stock and average sales unchanged?
- Why exclude today's partial day and include zero-sale days?
- Why does an approved order reduce suggestions while a draft does not?
- What happens if a sale fails after the balance update but before history insertion?
- How does the same-token retry differ from entering the same delivery with a new token?
- Why is a physical count rejected when its location version changes?
- How does a composite foreign key prevent cross-store references?
- Why does a historical sale retain its old price after product editing?

Course milestones: December 9 demonstration, CLO 363; December 13 submission at 11:59 p.m. Check BrightSpace for time, timezone and final instructions.
