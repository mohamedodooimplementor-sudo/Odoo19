from odoo.tests import HttpCase, TransactionCase, tagged


def _group_field(env):
    return 'group_ids' if 'group_ids' in env['res.users']._fields else 'groups_id'


def _portal_user(env, login, password=None):
    vals = {'name': login, 'login': login, 'email': login + '@example.com',
            _group_field(env): [(6, 0, [env.ref('base.group_portal').id])]}
    if password:
        vals['password'] = password
    return env['res.users'].create(vals)


class RepCase(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Partner = self.env['res.partner']
        self.rep_user = _portal_user(self.env, 'rep_one')
        self.rep = self.env['mo.sales.rep'].create({'name': 'Rep One', 'user_id': self.rep_user.id})
        self.cust_assigned = self.Partner.create({'name': 'Assigned Customer', 'customer_rank': 1})
        self.cust_other = self.Partner.create({'name': 'Other Customer', 'customer_rank': 1})
        self.rep.customer_ids = [(6, 0, [self.cust_assigned.id])]


@tagged('post_install', '-at_install')
class TestCustomerVisibility(RepCase):

    def test_supervisor_sees_customers_only(self):
        self.rep.can_view_all_customers = True
        found = self.Partner.search(self.rep.customers_domain())
        self.assertIn(self.cust_assigned, found)
        self.assertIn(self.cust_other, found)
        self.assertNotIn(self.rep_user.partner_id, found, 'a portal user is not a customer')
        self.assertNotIn(self.env.ref('base.user_admin').partner_id, found, 'an internal user is not a customer')
        self.assertNotIn(self.env.company.partner_id, found, 'the company is not a customer')

    def test_supervisor_does_not_see_employees(self):
        employee = self.env['hr.employee'].create({'name': 'Test Employee'})
        if not employee.work_contact_id:
            self.skipTest('this Odoo version has no work contact on employees')
        self.rep.can_view_all_customers = True
        self.assertNotIn(employee.work_contact_id, self.Partner.search(self.rep.customers_domain()))

    def test_normal_rep_sees_only_his_customers(self):
        self.rep.can_view_all_customers = False
        found = self.Partner.search(self.rep.customers_domain())
        self.assertIn(self.cust_assigned, found)
        self.assertNotIn(self.cust_other, found)
        # a customer whose Salesperson is the rep is his too
        self.cust_other.user_id = self.rep_user
        self.assertIn(self.cust_other, self.Partner.search(self.rep.customers_domain()))

    def test_access_check_follows_the_domain(self):
        self.rep.can_view_all_customers = False
        self.assertTrue(self.rep.can_access_partner(self.cust_assigned.id))
        self.assertFalse(self.rep.can_access_partner(self.cust_other.id))
        self.assertFalse(self.rep.can_access_partner(self.env.company.partner_id.id))


@tagged('post_install', '-at_install')
class TestSalespersonField(RepCase):

    def test_portal_user_can_be_selected_as_salesperson(self):
        for model in ('res.partner', 'sale.order'):
            domain = self.env[model]._fields['user_id'].domain
            domain = domain(self.env[model]) if callable(domain) else domain
            self.assertIn(self.rep_user, self.env['res.users'].search(domain), model)
        partner = self.Partner.create({'name': 'With Rep', 'user_id': self.rep_user.id})
        self.assertEqual(partner.user_id, self.rep_user)


@tagged('post_install', '-at_install')
class TestDuplicateCustomers(RepCase):

    def setUp(self):
        super().setUp()
        self.shop = self.Partner.create({'name': 'Nile Market', 'phone': '+20 100 123 4567', 'city': 'Alexandria'})

    def test_same_phone_any_format(self):
        for typed in ('01001234567', '0100-123-4567', '+201001234567'):
            self.assertIn(self.shop, self.Partner.mo_find_duplicates('Brand New', [typed]), typed)

    def test_other_phone_is_not_a_duplicate(self):
        self.assertNotIn(self.shop, self.Partner.mo_find_duplicates('Brand New', ['01221234567']))

    def test_same_name_same_city(self):
        self.assertIn(self.shop, self.Partner.mo_find_duplicates('nile market', [], 'ALEXANDRIA'))
        self.assertNotIn(self.shop, self.Partner.mo_find_duplicates('Nile Market', [], 'Cairo'))

    def test_wildcards_are_not_patterns(self):
        self.assertNotIn(self.shop, self.Partner.mo_find_duplicates('%', []))
        self.assertNotIn(self.shop, self.Partner.mo_find_duplicates('Nile_Market', []))


@tagged('post_install', '-at_install')
class TestPortalAccess(HttpCase):
    """A representative must not open a customer that is not his, even with the direct link."""

    def test_customer_page_is_protected(self):
        env = self.env
        user_a = _portal_user(env, 'rep_a', 'rep_a_pw')
        user_b = _portal_user(env, 'rep_b', 'rep_b_pw')
        rep_a = env['mo.sales.rep'].create({'name': 'Rep A', 'user_id': user_a.id})
        env['mo.sales.rep'].create({'name': 'Rep B', 'user_id': user_b.id})
        mine = env['res.partner'].create({'name': 'Visible Customer', 'customer_rank': 1})
        theirs = env['res.partner'].create({'name': 'Secret Customer', 'customer_rank': 1})
        rep_a.customer_ids = [(6, 0, [mine.id])]
        env.flush_all()

        self.authenticate('rep_a', 'rep_a_pw')
        own = self.url_open('/rep/customer/%s' % mine.id)
        self.assertEqual(own.status_code, 200)
        other = self.url_open('/rep/customer/%s' % theirs.id)
        self.assertEqual(other.status_code, 403)
        self.assertNotIn(b'Secret Customer', other.content)
