Bundled fallback copies (pure Python, unmodified):
  - reportlab 4.4.10  (BSD-3-Clause)  see LICENSES/ReportLab-LICENSE.txt
  - XlsxWriter 3.2.9  (BSD-2-Clause)  see LICENSES/XlsxWriter-LICENSE.txt

They are only used when the same library is NOT already installed in the
Python environment running Odoo, and only *during a report build of this
module* (see ../_libs.py): the folder is put on sys.path for that build and
removed again afterwards, together with the modules imported from it, so it
is never visible to Odoo's own code. Before use, every file is checked
against CHECKSUMS.sha256 (and no extra files are allowed). ReportLab
additionally needs Pillow, which Odoo itself already requires.
