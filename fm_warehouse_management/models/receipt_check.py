from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare


class FamilyMartReceiptCheck(models.Model):
    _name = 'fm.receipt.check'
    _description = 'FamilyMart - Phieu kiem tra nhan hang'
    _order = 'id desc'

    name = fields.Char(string='Mã phiếu', required=True, default='Kiểm tra nhận hàng')
    picking_id = fields.Many2one(
        'stock.picking', string='Phiếu nhận hàng Odoo', required=True,
        domain=[('picking_type_code', '=', 'incoming')], ondelete='restrict'
    )
    line_ids = fields.One2many('fm.receipt.check.line', 'check_id', string='Kiểm tra từng sản phẩm')
    note = fields.Text(string='Ghi chú và giải trình chênh lệch')
    state = fields.Selection([
        ('draft', 'Đang kiểm tra'), ('submitted', 'Chờ quản lý duyệt'),
        ('approved', 'Đã duyệt'), ('rejected', 'Yêu cầu kiểm tra lại'),
    ], default='draft', string='Trạng thái', readonly=True, copy=False)
    inspector_id = fields.Many2one('res.users', string='Người kiểm tra', readonly=True, copy=False)
    inspected_at = fields.Datetime(string='Thời gian kiểm tra', readonly=True, copy=False)
    approved_by = fields.Many2one('res.users', string='Người phê duyệt', readonly=True, copy=False)
    approved_at = fields.Datetime(string='Thời gian phê duyệt', readonly=True, copy=False)

    _unique_receipt_check = models.Constraint(
        'UNIQUE(picking_id)', 'Phiếu nhận này đã có biên bản kiểm tra.'
    )

    def _require_manager(self):
        if not self.env.user.has_group('stock.group_stock_manager'):
            raise UserError('Chỉ quản lý Inventory được phê duyệt kiểm tra nhận hàng.')

    def action_load_lines(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError('Chỉ lấy lại dòng khi phiếu đang kiểm tra.')
        if self.line_ids:
            raise UserError('Phiếu đã có dòng kiểm tra. Không tự thay thế dữ liệu đã nhập.')
        if self.picking_id.picking_type_code != 'incoming':
            raise UserError('Chỉ được kiểm tra phiếu nhận hàng.')
        if self.picking_id.state in ('done', 'cancel'):
            raise UserError('Phiếu nhận hàng đã hoàn tất/hủy, không thể lập kiểm tra trước nhận.')
        moves = self.picking_id.move_ids.filtered(lambda m: m.state != 'cancel')
        if not moves:
            raise UserError('Phiếu nhận hàng chưa có sản phẩm.')
        self.write({'line_ids': [(0, 0, {'move_id': move.id}) for move in moves]})
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_submit(self):
        self.ensure_one()
        if self.state not in ('draft', 'rejected'):
            raise UserError('Trạng thái hiện tại không cho phép gửi duyệt.')
        moves = self.picking_id.move_ids.filtered(lambda m: m.state != 'cancel')
        if not moves or set(self.line_ids.mapped('move_id').ids) != set(moves.ids):
            raise UserError('Danh sách kiểm tra phải bao gồm tất cả sản phẩm của phiếu nhận.')
        for line in self.line_ids:
            if float_compare(line.accepted_qty + line.damaged_qty, line.observed_qty,
                             precision_rounding=line.product_id.uom_id.rounding) != 0:
                raise UserError('Tổng số đạt + hư hỏng phải bằng số đếm: %s' % line.product_id.display_name)
            if line.has_difference and not (line.note or self.note):
                raise UserError('Có chênh lệch/hàng hư hỏng. Hãy ghi nguyên nhân trước khi duyệt.')
        self.write({
            'state': 'submitted', 'inspector_id': self.env.user.id,
            'inspected_at': fields.Datetime.now(),
        })

    def action_approve(self):
        self.ensure_one()
        self._require_manager()
        if self.state != 'submitted':
            raise UserError('Phiếu chưa được gửi duyệt.')
        if self.picking_id.state in ('done', 'cancel'):
            raise UserError('Phiếu nhận hàng đã hoàn thành/hủy. Không thể duyệt kiểm tra trước nhận.')
        self.write({
            'state': 'approved', 'approved_by': self.env.user.id,
            'approved_at': fields.Datetime.now(),
        })

    def action_reject(self):
        self.ensure_one()
        self._require_manager()
        if self.state != 'submitted':
            raise UserError('Chỉ từ chối phiếu đang chờ duyệt.')
        self.state = 'rejected'

    def action_open_receipt(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': 'Phiếu nhận hàng Odoo',
            'res_model': 'stock.picking', 'view_mode': 'form', 'res_id': self.picking_id.id,
        }

    def write(self, vals):
        if 'state' in vals and vals['state'] == 'approved' and not self.env.user.has_group('stock.group_stock_manager'):
            raise UserError('Chỉ quản lý Inventory được phê duyệt kiểm tra nhận hàng.')
        protected = {'picking_id', 'line_ids', 'note'}
        if protected.intersection(vals) and any(r.state in ('submitted', 'approved') for r in self):
            raise UserError('Phiếu đã gửi duyệt: không sửa nội dung kiểm tra.')
        return super().write(vals)


class FamilyMartReceiptCheckLine(models.Model):
    _name = 'fm.receipt.check.line'
    _description = 'FamilyMart - Dong kiem tra nhan hang'

    check_id = fields.Many2one('fm.receipt.check', string='Biên bản kiểm tra', required=True, ondelete='cascade')
    move_id = fields.Many2one('stock.move', string='Dòng phiếu nhận', required=True, ondelete='restrict')
    product_id = fields.Many2one('product.product', related='move_id.product_id', string='Sản phẩm', readonly=True)
    expected_qty = fields.Float(related='move_id.product_uom_qty', string='Số trên phiếu', readonly=True)
    observed_qty = fields.Float(string='Số đếm thực tế', default=0)
    accepted_qty = fields.Float(string='Số đạt', default=0)
    damaged_qty = fields.Float(string='Số lỗi/trả lại', default=0)
    expiry_note = fields.Char(string='HSD theo bao bì')
    note = fields.Char(string='Nguyên nhân/chất lượng')
    has_difference = fields.Boolean(string='Có chênh lệch', compute='_compute_difference')

    _unique_receipt_move = models.Constraint(
        'UNIQUE(check_id, move_id)', 'Không được kiểm tra trùng dòng phiếu nhận.'
    )

    @api.depends('expected_qty', 'observed_qty', 'damaged_qty')
    def _compute_difference(self):
        for line in self:
            line.has_difference = (
                abs(line.expected_qty - line.observed_qty) > 0.00001
                or line.damaged_qty > 0
            )

    @api.constrains('move_id', 'check_id')
    def _check_move(self):
        for line in self:
            if line.move_id and line.check_id and line.move_id.picking_id != line.check_id.picking_id:
                raise ValidationError('Dòng kiểm tra không thuộc phiếu nhận đã chọn.')

    @api.constrains('observed_qty', 'accepted_qty', 'damaged_qty')
    def _check_qty(self):
        for line in self:
            if min(line.observed_qty, line.accepted_qty, line.damaged_qty) < 0:
                raise ValidationError('Không được nhập số lượng âm.')

    def write(self, vals):
        if any(line.check_id.state in ('submitted', 'approved') for line in self):
            raise UserError('Không sửa dòng đã gửi duyệt.')
        return super().write(vals)

    def unlink(self):
        if any(line.check_id.state in ('submitted', 'approved') for line in self):
            raise UserError('Không xóa dòng đã gửi duyệt.')
        return super().unlink()
