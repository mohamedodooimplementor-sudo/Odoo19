# custom_product_reference_by_category

This Odoo 18 module assigns product internal references based on the sequence defined in the product's category.

## Features
- Adds a 'Sequence' field to Product Category.
- When a product is created with an empty Internal Reference, it uses the category's sequence (if set).

## Usage
1. Go to Inventory → Configuration → Product Categories.
2. Edit or create a category, set its Sequence field.
3. When creating a product under that category, the Internal Reference (default_code) will be auto-generated.
