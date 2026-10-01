from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Product Check 1 / 2 used to add materials / finished product automatically (hard-coded).
    That is now configured on the template, so add the automatic item to the default templates."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    for xmlid, line_type in (('pre_production.tmpl_pc1', 'material'), ('pre_production.tmpl_pc2', 'finished')):
        tmpl = env.ref(xmlid, raise_if_not_found=False)
        if tmpl and not tmpl.line_ids.filtered(lambda l: l.line_type == line_type):
            env['pp.quality.template.line'].create({
                'template_id': tmpl.id, 'line_type': line_type,
                'sequence': max(tmpl.line_ids.mapped('sequence') or [0]) + 10})
