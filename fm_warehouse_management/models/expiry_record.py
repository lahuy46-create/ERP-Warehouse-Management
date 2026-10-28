from odoo import api, fields, models
from odoo.exceptions import UserError


class FamilyMartExpiryRecord(models.Model):
    _name = 'fm.expiry.record'
    _description = 'FamilyMart - So theo doi han su dung (thu cong)'
    _order = 'expiry_date asc, id desc'
    _rec_name = 'product_id'

    product_id = fields.Many2one('product.product', string='Sản phẩm', required=True, ondelete='restrict')
    location_id = fields.Many2one('stock.location', string='Vị trí ghi nhận', required=True, domain=[('usage', '=', 'internal')])
    expiry_date = fields.Date(string='Hạn sử dụng', required=True)
    quantity_observed = fields.Float(string='Số lượng quan sát (không tự đồng bộ kho)', required=True, default=1)
    note = fields.Text(string='Ghi chú/lô trên bao bì')
    state = fields.Selection([('open', 'Cần theo dõi'), ('handled', 'Đã xử lý')], default='open', string='Tình trạng', readonly=True)
    days_left = fields.Integer(string='Ngày còn lại', compute='_compute_alert')
    alert_level = fields.Selection([
        ('expired', 'Đã hết hạn'), ('7', 'Trong 7 ngày'), ('15', 'Trong 15 ngày'),
        ('30', 'Trong 30 ngày'), ('ok', 'Trên 30 ngày'),
    ], string='Cảnh báo HSD', compute='_compute_alert')

    _positive_observed = models.Constraint('CHECK (quantity_observed > 0)', 'Số lượng quan sát phải lớn hơn 0.')

    @api.depends('expiry_date')
    def _compute_alert(self):
        today = fields.Date.context_today(self)
        for rec in self:
            days = (rec.expiry_date - today).days if rec.expiry_date else 99999
            rec.days_left = days
            rec.alert_level = ('expired' if days < 0 else '7' if days <= 7 else
                               '15' if days <= 15 else '30' if days <= 30 else 'ok')

    def write(self, vals):
        if 'state' in vals and not self.env.user.has_group('stock.group_stock_manager'):
            raise UserError('Chỉ quản lý được thay đổi trạng thái xử lý HSD.')
        return super().write(vals)

    def action_mark_handled(self):
        if not self.env.user.has_group('stock.group_stock_manager'):
            raise UserError('Chỉ quản lý Inventory được xác nhận đã xử lý HSD.')
        self.write({'state': 'handled'})
        return {'type': 'ir.actions.client', 'tag': 'reload'}
