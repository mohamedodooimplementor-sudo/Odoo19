from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Exam patient became a customer (res.partner). Convert the old free-text names:
    reuse an existing contact with the same name, otherwise create one."""
    cr.execute("""SELECT 1 FROM information_schema.columns
                  WHERE table_name = 'rc_exam_consumption' AND column_name = 'patient_name'""")
    if not cr.fetchone():
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute("""SELECT DISTINCT TRIM(patient_name) FROM rc_exam_consumption
                  WHERE patient_name IS NOT NULL AND TRIM(patient_name) != '' AND patient_id IS NULL""")
    for (name,) in cr.fetchall():
        cr.execute("SELECT id FROM res_partner WHERE name = %s AND active ORDER BY id LIMIT 1", (name,))
        row = cr.fetchone()
        partner_id = row[0] if row else env['res.partner'].create({'name': name}).id
        cr.execute("""UPDATE rc_exam_consumption SET patient_id = %s
                      WHERE TRIM(patient_name) = %s AND patient_id IS NULL""", (partner_id, name))
