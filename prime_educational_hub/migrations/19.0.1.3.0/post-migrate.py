# -*- coding: utf-8 -*-
"""
'room' used to be a free-text Char field on education.group,
education.group.schedule and education.session. It is now a proper Many2one
to the new education.room master model (education_room_id in each table's
Python field is 'room_id'). Odoo's ORM only ever ADDS columns for new
fields -- it never renames/drops the old 'room' varchar column just because
the field was renamed, so at this point in the upgrade the old text is still
sitting there untouched. This migration:
  1. Collects every distinct non-empty room name from all three tables.
  2. Creates one education.room record per distinct name.
  3. Points the new room_id column at the right room for every existing
     group / schedule slot / session.
  4. Drops the now-unused legacy 'room' columns.
"""
import logging

_logger = logging.getLogger(__name__)

TABLES = ('education_group', 'education_group_schedule', 'education_session')


def _column_exists(cr, table, column):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
    """, (table, column))
    return bool(cr.fetchone())


def migrate(cr, version):
    _migrate_rooms(cr)
    _seed_cash_accounts(cr)


def _migrate_rooms(cr):
    # Only tables/columns that still have the legacy text column need handling
    # (a fresh install of this module version never had it in the first place).
    legacy_tables = [t for t in TABLES if _column_exists(cr, t, 'room')]
    if not legacy_tables:
        return

    env = _api_env(cr)
    Room = env['education.room']

    distinct_names = set()
    for table in legacy_tables:
        cr.execute(f"SELECT DISTINCT room FROM {table} WHERE room IS NOT NULL AND trim(room) != ''")
        distinct_names.update(row[0].strip() for row in cr.fetchall())

    room_id_by_name = {}
    for name in sorted(distinct_names):
        existing = Room.search([('name', '=', name)], limit=1)
        room_id_by_name[name] = existing.id if existing else Room.create({'name': name}).id

    for table in legacy_tables:
        cr.execute(f"SELECT id, room FROM {table} WHERE room IS NOT NULL AND trim(room) != ''")
        for rec_id, room_text in cr.fetchall():
            room_id = room_id_by_name.get(room_text.strip())
            if room_id:
                cr.execute(f"UPDATE {table} SET room_id = %s WHERE id = %s", (room_id, rec_id))
        # The legacy column has done its job -- drop it to avoid confusion.
        cr.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS room")

    if distinct_names:
        _logger.info(
            'prime_educational_hub: migrated %s distinct room name(s) into education.room '
            'and remapped room_id across %s.', len(distinct_names), ', '.join(legacy_tables))


def _seed_cash_accounts(cr):
    """The standalone accounting feature (education.expense / education.cash.account)
    was added to this module without a dedicated version bump, so on an upgrade from
    an older database the noupdate="1" default-data records (Main Cash Drawer / Main
    Bank Account, and the cash_account_id link on each stock payment method) never
    get (re)applied -- noupdate data only runs on a fresh install. Without this, the
    Cash Book / treasury balance reports would silently show zero for every existing
    installation. This creates the two accounts (if missing) and links any payment
    method that doesn't have one yet, without touching methods an admin already
    configured manually."""
    env = _api_env(cr)
    CashAccount = env['education.cash.account']
    PaymentMethod = env['education.payment.method']

    main_cash = CashAccount.search([('name', '=', 'Main Cash Drawer')], limit=1)
    if not main_cash:
        main_cash = CashAccount.create({'name': 'Main Cash Drawer', 'account_type': 'cash', 'sequence': 10})
    main_bank = CashAccount.search([('name', '=', 'Main Bank Account')], limit=1)
    if not main_bank:
        main_bank = CashAccount.create({'name': 'Main Bank Account', 'account_type': 'bank', 'sequence': 20})

    bank_like_codes = ('bank_transfer', 'card')
    methods = PaymentMethod.search([('cash_account_id', '=', False)])
    for method in methods:
        method.cash_account_id = main_bank.id if method.code in bank_like_codes else main_cash.id
    if methods:
        _logger.info(
            'prime_educational_hub: linked %s existing payment method(s) to a default '
            'cash/bank account.', len(methods))


def _api_env(cr):
    from odoo import api, SUPERUSER_ID
    return api.Environment(cr, SUPERUSER_ID, {})
