from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare


class FamilyMartStocktakeRequest(models.Model):
    _name = 'fm.stocktake.request'
    _description = 'FamilyMart - Kiem ke va phe duyet dieu chinh'
    _order = 'id desc'

    name = fields.Char(string='Mã/đợt kiểm kê', required=True)
    product_id = fields.Many2one('product.product', string='Sản phẩm', required=True, ondelete='restrict')
    location_id = fields.Many2one('stock.location', string='Vị trí kiểm kê', required=True,
        domain=[('usage', '=', 'internal')], ondelete='restrict')
    barcode_scanned = fields.Char(string='Barcode đã quét/nhập')
    counted_qty = fields.Float(string='Số lượng thực đếm', required=True)
    system_qty = fields.Float(string='Tồn hệ thống khi gửi duyệt', readonly=True, copy=False)
    difference_qty = fields.Float(string='Chênh lệch', compute='_compute_difference')
    reason = fields.Text(string='Giải trình chênh lệch')
    state = fields.Selection([
        ('draft', 'Đang kiểm đếm'), ('submitted', 'Chờ duyệt'),
        ('approved', 'Đã duyệt, chờ điều chỉnh Inventory'),
        ('rejected', 'Yêu cầu kiểm lại'), ('applied', 'Đã đối chiếu hoàn tất'),
    ], default='draft', string='Trạng thái', readonly=True, copy=False)
    counted_by = fields.Many2one('res.users', string='Người kiểm kê', readonly=True, copy=False)
    approved_by = fields.Many2one('res.users', string='Người duyệt', readonly=True, copy=False)
    approved_at = fields.Datetime(string='Thời điểm duyệt', readonly=True, copy=False)

    @api.depends('counted_qty', 'system_qty')
    def _compute_difference(self):
        for rec in self:
            rec.difference_qty = rec.counted_qty - rec.system_qty

    @api.constrains('counted_qty')
    def _validate_counted(self):
        for rec in self:
            if rec.counted_qty < 0:
                raise ValidationError('Số lượng kiểm đếm không được âm.')

    def _exact_stock_qty(self):
        self.ensure_one()
        quants = self.env['stock.quant'].sudo().search([
            ('product_id', '=', self.product_id.id),
            ('location_id', '=', self.location_id.id),
        ])
        return sum(quants.mapped('quantity'))

    def _manager(self):
        if not self.env.user.has_group('stock.group_stock_manager'):
            raise UserError('Chỉ quản lý Inventory được phê duyệt/đối chiếu kiểm kê.')

    def action_submit(self):
        self.ensure_one()
        if self.state not in ('draft', 'rejected'):
            raise UserError('Phiếu không còn ở trạng thái kiểm đếm.')
        if self.location_id.usage != 'internal':
            raise UserError('Chỉ kiểm kê tại vị trí kho/kệ nội bộ.')
        if self.product_id.tracking != 'none':
            raise UserError('Mẫu phiếu này chỉ áp dụng By Quantity; hàng theo Lot cần kiểm theo lô.')
        if self.barcode_scanned and self.barcode_scanned.strip() != (self.product_id.barcode or '').strip():
            raise UserError('Barcode đã quét không khớp sản phẩm đã chọn.')
        current_qty = self._exact_stock_qty()
        if float_compare(self.counted_qty, current_qty,
                         precision_rounding=self.product_id.uom_id.rounding) != 0 and not self.reason:
            raise UserError('Có chênh lệch tồn. Hãy nhập nguyên nhân giải trình.')
        self.write({'system_qty': current_qty, 'counted_by': self.env.user.id, 'state': 'submitted'})

    def action_approve(self):
        self.ensure_one()
        self._manager()
        if self.state != 'submitted':
            raise UserError('Chỉ duyệt phiếu đang chờ duyệt.')
        current = self._exact_stock_qty()
        if float_compare(current, self.system_qty, precision_rounding=self.product_id.uom_id.rounding) != 0:
            raise UserError('Tồn kho đã thay đổi kể từ khi đếm. Cần kiểm lại trước khi duyệt.')
        self.write({'state': 'approved', 'approved_by': self.env.user.id,
                    'approved_at': fields.Datetime.now()})

    def action_reject(self):
        self.ensure_one()
        self._manager()
        if self.state != 'submitted':
            raise UserError('Chỉ từ chối phiếu đang chờ duyệt.')
        self.state = 'rejected'

    def action_open_inventory(self):
        self.ensure_one()
        self._manager()
        if self.state != 'approved':
            raise UserError('Cần phê duyệt trước khi mở điều chỉnh Inventory.')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Kiểm kê Odoo: nhập Counted và Apply',
            'res_model': 'stock.quant', 'view_mode': 'list,form',
            'domain': [('product_id', '=', self.product_id.id),
                       ('location_id', '=', self.location_id.id)],
            'context': {'inventory_mode': True},
        }

    def action_mark_applied(self):
        self.ensure_one()
        self._manager()
        if self.state != 'approved':
            raise UserError('Chỉ đối chiếu phiếu đã phê duyệt.')
        current = self._exact_stock_qty()
        if float_compare(current, self.counted_qty,
                         precision_rounding=self.product_id.uom_id.rounding) != 0:
            raise UserError('Tồn thực tế trên Odoo vẫn khác số kiểm kê. Hãy Apply trên Inventory trước.')
        self.state = 'applied'

    def write(self, vals):
        if 'state' in vals and vals['state'] in ('approved', 'applied') and not self.env.user.has_group('stock.group_stock_manager'):
            raise UserError('Chỉ quản lý Inventory được duyệt/hoàn tất kiểm kê.')
        protected = {'product_id', 'location_id', 'barcode_scanned', 'counted_qty', 'reason'}
        if protected.intersection(vals) and any(rec.state in ('submitted', 'approved', 'applied') for rec in self):
            raise UserError('Không sửa nội dung phiếu đã gửi duyệt.')
        return super().write(vals)
