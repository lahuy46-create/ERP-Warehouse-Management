from odoo import fields, models
from odoo.exceptions import UserError


class FamilyMartIssueRecord(models.Model):
    _name = 'fm.issue.record'
    _description = 'FamilyMart - Bao cao ngoai le kho'
    _order = 'id desc'

    name = fields.Char(string='Tiêu đề', required=True)
    issue_type = fields.Selection([
        ('short', 'Thiếu hàng khi nhận'), ('excess', 'Thừa hàng khi nhận'),
        ('damaged', 'Hư hỏng'), ('expired', 'Hết hạn'),
        ('stocktake', 'Chênh lệch kiểm kê'), ('other', 'Khác'),
    ], string='Loại vấn đề', required=True)
    product_id = fields.Many2one('product.product', string='Sản phẩm')
    location_id = fields.Many2one('stock.location', string='Vị trí', domain=[('usage', '=', 'internal')])
    quantity = fields.Float(string='Số lượng liên quan', default=1)
    note = fields.Text(string='Diễn giải')
    state = fields.Selection([('open', 'Mới báo'), ('review', 'Đang xử lý'), ('closed', 'Đã đóng')], default='open', readonly=True)

    def write(self, vals):
        if 'state' in vals and not self.env.user.has_group('stock.group_stock_manager'):
            raise UserError('Chỉ quản lý được thay đổi trạng thái báo cáo.')
        return super().write(vals)

    def action_review(self):
        if not self.env.user.has_group('stock.group_stock_manager'):
            raise UserError('Chỉ quản lý Inventory được duyệt ngoại lệ.')
        self.state = 'review'

    def action_close(self):
        if not self.env.user.has_group('stock.group_stock_manager'):
            raise UserError('Chỉ quản lý Inventory được đóng ngoại lệ.')
        self.state = 'closed'
