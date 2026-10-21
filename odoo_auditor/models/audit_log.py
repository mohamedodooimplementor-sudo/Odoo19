from odoo import api, fields, models
from odoo.exceptions import UserError


class AuditorLog(models.Model):
    """Protected, append-only log of changes to the Auditor's own records.

    It does NOT track changes in other Odoo modules.
    """
    _name = 'odoo.auditor.log'
    _description = 'Auditor Log'
    _order = 'id desc'

    timestamp = fields.Datetime(default=fields.Datetime.now, readonly=True, index=True)
    user_id = fields.Many2one('res.users', default=lambda s: s.env.user, readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    operation = fields.Selection([('create', 'Create'), ('write', 'Update'), ('transition', 'State Transition'),
                                  ('unlink_blocked', 'Blocked Deletion')], readonly=True)
    model_name = fields.Char(readonly=True, index=True)
    res_id = fields.Integer(readonly=True)
    res_name = fields.Char(readonly=True)
    old_values = fields.Text(readonly=True)
    new_values = fields.Text(readonly=True)
    reason = fields.Char(readonly=True)
    finding_id = fields.Many2one('odoo.auditor.finding', ondelete='set null', readonly=True)

    def write(self, vals):
        raise UserError(self.env._("The audit log is protected and cannot be modified."))

    def unlink(self):
        if self.env.context.get('module_uninstall'):
            return super().unlink()
        raise UserError(self.env._("The audit log is protected and cannot be deleted."))

    @api.model
    def log(self, operation, record, old=None, new=None, reason=False):
        finding = record if record._name == 'odoo.auditor.finding' else (
            record.finding_id if 'finding_id' in record._fields else self.env['odoo.auditor.finding'])
        return self.sudo().create({
            'operation': operation,
            'user_id': self.env.uid,
            'company_id': record.company_id.id if 'company_id' in record._fields else False,
            'model_name': record._name,
            'res_id': record.id,
            'res_name': record.display_name,
            'old_values': str(old) if old is not None else False,
            'new_values': str(new) if new is not None else False,
            'reason': reason or self.env.context.get('audit_reason') or False,
            'finding_id': finding.id if finding and finding._name == 'odoo.auditor.finding' else False,
        })


class AuditorLoggedMixin(models.AbstractModel):
    _name = 'odoo.auditor.logged.mixin'
    _description = 'Audit logging mixin'

    _log_fields = ()

    def _log_val(self, fname):
        value = self[fname]
        if isinstance(value, models.BaseModel):
            return ', '.join(value.mapped('display_name'))
        return str(value) if value is not None else ''

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            self.env['odoo.auditor.log'].log('create', rec)
        return records

    def write(self, vals):
        fnames = [f for f in vals if f in self._log_fields]
        old = {rec.id: {f: rec._log_val(f) for f in fnames} for rec in self} if fnames else {}
        res = super().write(vals)
        for rec in (self if fnames else self.browse()):
            new = {f: rec._log_val(f) for f in fnames}
            if new != old[rec.id]:
                op = 'transition' if 'state' in fnames else 'write'
                before = {k: v for k, v in old[rec.id].items() if v != new[k]}
                after = {k: v for k, v in new.items() if k in before}
                self.env['odoo.auditor.log'].log(op, rec, old=before, new=after)
        return res
