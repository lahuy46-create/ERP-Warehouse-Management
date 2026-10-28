from odoo import fields, models
from odoo.exceptions import UserError


class FamilyMartStorageRule(models.Model):
    _name = 'fm.storage.rule'
    _description = 'FamilyMart - Goi y vi tri luu tru (quy tac thu cong)'
    _rec_name = 'product_id'

    product_id = fields.Many2one('product.product', string='Sản phẩm', required=True, ondelete='restrict')
    zone = fields.Selection([
        ('normal', 'Kho thường KT'), ('cold', 'Kho lạnh KL'),
        ('display', 'Kệ trưng bày TB'), ('hold', 'Khu chờ xử lý HH'),
    ], string='Loại khu', required=True, default='normal')
    preferred_location_id = fields.Many2one('stock.location', string='Vị trí đề xuất', required=True,
        domain=[('usage', '=', 'internal')])
    note = fields.Char(string='Ghi chú sắp xếp')

    _unique_product_rule = models.Constraint(
        'UNIQUE(product_id)', 'Mỗi sản phẩm chỉ có một vị trí lưu trữ ưu tiên.'
    )

    def action_open_location(self):
        self.ensure_one()
        if not self.preferred_location_id:
            raise UserError('Chưa có vị trí ưu tiên.')
        return {'type': 'ir.actions.act_window', 'name': 'Vị trí kho/kệ',
                'res_model': 'stock.location', 'view_mode': 'form',
                'res_id': self.preferred_location_id.id}
