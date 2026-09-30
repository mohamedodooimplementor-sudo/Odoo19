# custom_partner_reference_sequence

This Odoo 19 module automatically generates reference codes for partners
(customers, suppliers, and plain contacts).

## Features
- Customers get codes starting with `C` (e.g. C0001).
- Suppliers get codes starting with `S` (e.g. S0001).
- Plain contacts (neither customer nor supplier) get codes starting with
  `P` (e.g. P0001).
- Works only if the `ref` field is empty when creating a partner.
- If a user clears the `ref` field on an existing partner and saves it
  blank, it is automatically regenerated so a partner never ends up
  permanently without a reference.
- **Multi-company**: on install, every existing company automatically
  gets its own independent numbering (Company A starts at C0001, Company
  B also starts at C0001, etc.) via a `post_init_hook`. A single global
  sequence is still shipped as a fallback for single-company databases.
- The `Reference` field is shown as the first column in the Contacts
  list view, and also appears on the Contacts kanban cards.
- A database-level uniqueness constraint (`ref` + `company_id`) prevents
  duplicate references **for partners that have a company set**. Individual
  contacts without a company assigned are not restricted by this
  constraint, to avoid breaking existing data on upgrade.

## Notes / caveats
- If you are installing this on a database that already has many
  partners with a `company_id` set and duplicate/blank `ref` values,
  the SQL constraint above may block the update — clean up duplicates
  first, or remove the constraint from `models/res_partner.py` if you
  don't need it.
- New companies created **after** installation will not automatically
  get their own sequence; only the companies that existed at install
  time are covered by the `post_init_hook`. Re-run it manually (or
  create the sequences yourself) if you add companies later.
