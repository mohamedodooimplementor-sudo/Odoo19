# Check Management (Odoo 19)

Incoming / outgoing checks with kanban pipeline, automatic accounting entries, invoice
reconciliation, analysis reports, a chart dashboard and a configurable check-printing template.

## After installing
1. Checks > Configuration > **Accounting Settings** > *Create Missing Accounts* (or pick your own accounts).
   Leave "Checks Under Collection" empty to use a single account for incoming checks.
2. Checks > Configuration > **Print Templates**: adjust the positions (mm) of the date, payee, amount in
   words and figures to your bank's check leaf. Upload a scan of a blank leaf to align visually.

## Printing requirements
* Official **wkhtmltopdf 0.12.6.1 with patched Qt** (the build Odoo itself requires). Distribution
  packages (Debian/Ubuntu apt) are not patched and print at ~77% size.
* A font with Arabic glyphs on the server (Tahoma/Arial, or DejaVu Sans / Noto) for Arabic checks.
* The page size comes from the paper format "Check Leaf (175 x 80 mm)" - edit it in
  Settings > Technical > Paper Format if your leaf has another size.
