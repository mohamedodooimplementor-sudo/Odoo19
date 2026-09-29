# custom_product_reference_by_category

This Odoo 19 module assigns product internal references based on the
sequence defined on the product's category.

## Features
- Adds a `Sequence` field to Product Category (shown on both the form
  and the list view).
- When a product is created with an empty Internal Reference
  (`default_code`), it uses the category's sequence if set.
- **Category is now required** on the product form, and enforced at the
  model level too (so it can't be skipped via the API or an import).
- **Parent category fallback**: if a category has no sequence of its
  own, the module walks up the parent category chain and uses the
  first sequence it finds. This means you only need to configure a
  sequence on a top-level category to have it apply to all its
  sub-categories, unless a sub-category overrides it with its own.
- **Protected auto-generated codes**: once a reference has been
  generated automatically, regular users can no longer edit it by hand
  (they'll get a clear error). Administrators (Settings/Technical
  group) can still override it if genuinely needed.
- **Variants**: when a product template ends up with more than one
  variant, each variant that still shares the template's auto-generated
  code gets a numbered suffix (e.g. `C0001-01`, `C0001-02`, ...) so
  variants remain individually identifiable. Variants given an explicit
  code of their own are left untouched.
- A database-level uniqueness constraint prevents two products in the
  same company from ending up with the same Internal Reference.

## Usage
1. Go to Inventory → Configuration → Product Categories.
2. Edit or create a category, set its Sequence field (or leave it
   blank to inherit from a parent category).
3. When creating a product under that category, the Internal Reference
   (`default_code`) is auto-generated.

## Notes / caveats
- If you are installing this on a database that already has products
  without a category, or duplicate Internal References, you must fix
  that data first — the required-category rule and the uniqueness
  constraint will otherwise block the module update.
- The variant-suffixing logic is a best-effort convenience feature. It
  runs when a variant record is created; depending on how variants are
  generated in your exact workflow (attribute lines vs. manual
  creation), you may want to test it against your own setup before
  relying on it in production.
