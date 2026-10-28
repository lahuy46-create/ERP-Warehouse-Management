from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class FamilyMartDispositionCase(models.Model):
    _name = 'fm.disposition.case'
    _description = 'FamilyMart - Xu ly hang loi, het han, hoan tra, xuat huy'
    _order = 'id desc'

    name = fields.Char(string='Mã hồ sơ', required=True)
    issue_type = fields.Selection([
        ('damaged', 'Hàng hư hỏng'), ('expired', 'Hàng hết hạn'),
        ('return', 'Hàng cần trả nhà cung cấp'),
    ], string='Loại hàng', required=True)
    resolution = fields.Selection([
        ('quarantine', 'Chuyển khu HH chờ xử lý'),
        ('scrap', 'Xuất hủy (Scrap)'),
        ('return', 'Hoàn trả nhà cung cấp'),
    ], string='Phương án xử lý', required=True)
    product_id = fields.Many2one('product.product', string='Sản phẩm', required=True, ondelete='restrict')
    quantity = fields.Float(string='Số lượng cần xử lý', required=True, default=1)
    source_location_id = fields.Many2one('stock.location', string='Vị trí hàng hiện tại', required=True,
        domain=[('usage', '=', 'internal')])
    hold_location_id = fields.Many2one('stock.location', string='Khu HH',
        domain=[('usage', '=', 'internal')])
    receipt_picking_id = fields.Many2one('stock.picking', string='Phiếu nhận hàng gốc (khi trả NCC)',
        domain=[('picking_type_code', '=', 'incoming')])
    note = fields.Text(string='Nguyên nhân / mô tả / HSD bao bì', required=True)
    quarantine_picking_id = fields.Many2one('stock.picking', string='Phiếu chuyển đến HH', readonly=True, copy=False)
    scrap_id = fields.Many2one('stock.scrap', string='Phiếu Scrap đã xử lý', copy=False)
    return_picking_id = fields.Many2one('stock.picking', string='Phiếu hoàn trả nhà cung cấp', copy=False)
    state = fields.Selection([
        ('draft', 'Mới báo'), ('submitted', 'Chờ duyệt'),
        ('approved', 'Đã duyệt, chờ xử lý Inventory'),
        ('rejected', 'Yêu cầu bổ sung'), ('closed', 'Đã xử lý xong'),
    ], string='Trạng thái', default='draft', readonly=True, copy=False)
    reported_by = fields.Many2one('res.users', string='Người báo cáo', readonly=True, copy=False)
    approved_by = fields.Many2one('res.users', string='Người duyệt', readonly=True, copy=False)
    approved_at = fields.Datetime(string='Thời gian duyệt', readonly=True, copy=False)

    @api.constrains('quantity')
    def _check_quantity(self):
        for rec in self:
            if rec.quantity <= 0:
                raise ValidationError('Số lượng cần xử lý phải lớn hơn 0.')

    def _manager(self):
        if not self.env.user.has_group('stock.group_stock_manager'):
            raise UserError('Chỉ quản lý Inventory được phê duyệt và xử lý.')

    def action_submit(self):
        self.ensure_one()
        if self.state not in ('draft', 'rejected'):
            raise UserError('Hồ sơ đã được gửi duyệt.')
        if self.source_location_id.usage != 'internal':
            raise UserError('Nguồn xử lý phải là kho/kệ nội bộ.')
        if self.resolution == 'quarantine':
            if not self.hold_location_id or self.hold_location_id.usage != 'internal':
                raise UserError('Hãy chọn khu HH nội bộ.')
            if self.source_location_id == self.hold_location_id:
                raise UserError('Nguồn và khu HH không được trùng nhau.')
        if self.resolution == 'return' and not self.receipt_picking_id:
            raise UserError('Cần chọn phiếu nhận gốc trước khi đề nghị trả NCC.')
        self.write({'state': 'submitted', 'reported_by': self.env.user.id})

    def action_approve(self):
        self.ensure_one()
        self._manager()
        if self.state != 'submitted':
            raise UserError('Hồ sơ chưa được gửi duyệt.')
        self.write({'state': 'approved', 'approved_by': self.env.user.id,
                    'approved_at': fields.Datetime.now()})

    def action_reject(self):
        self.ensure_one()
        self._manager()
        if self.state != 'submitted':
            raise UserError('Chỉ từ chối hồ sơ đang chờ duyệt.')
        self.state = 'rejected'

    def action_prepare_quarantine(self):
        self.ensure_one()
        self._manager()
        if self.state != 'approved' or self.resolution != 'quarantine':
            raise UserError('Cần phê duyệt phương án chuyển khu HH trước.')
        if self.quarantine_picking_id:
            raise UserError('Đã tạo phiếu chuyển khu HH: %s' % self.quarantine_picking_id.display_name)
        if self.product_id.tracking != 'none':
            raise UserError('Mẫu chuyển khu HH chỉ hỗ trợ By Quantity; hàng Lot/Serial thao tác trong Inventory.')
        picking_type = self.env['stock.picking.type'].search([
            ('code', '=', 'internal'),
            ('company_id', 'in', [False, self.env.company.id]),
        ], limit=1)
        if not picking_type:
            raise UserError('Chưa có loại phiếu Internal Transfer trong Odoo.')
        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'origin': 'FM-DISPOSITION-%s' % self.id,
            'location_id': self.source_location_id.id,
            'location_dest_id': self.hold_location_id.id,
            'move_ids': [(0, 0, {
                'name': 'Chuyển khu chờ xử lý: %s' % self.product_id.display_name,
                'product_id': self.product_id.id,
                'product_uom_qty': self.quantity,
                'product_uom': self.product_id.uom_id.id,
                'location_id': self.source_location_id.id,
                'location_dest_id': self.hold_location_id.id,
            })],
        })
        self.quarantine_picking_id = picking.id
        return {'type': 'ir.actions.act_window', 'name': 'Phiếu chuyển khu HH (nháp)',
                'res_model': 'stock.picking', 'view_mode': 'form', 'res_id': picking.id}

    def action_open_scrap(self):
        self.ensure_one()
        self._manager()
        if self.state != 'approved' or self.resolution != 'scrap':
            raise UserError('Hồ sơ xuất hủy phải được phê duyệt trước.')
        if self.scrap_id:
            return {'type': 'ir.actions.act_window', 'name': 'Phiếu Scrap',
                    'res_model': 'stock.scrap', 'view_mode': 'form', 'res_id': self.scrap_id.id}
        # Open a native Odoo scrap form; operator must Save/Validate then link its reference.
        return {'type': 'ir.actions.act_window', 'name': 'Tạo phiếu Scrap Odoo',
                'res_model': 'stock.scrap', 'view_mode': 'form',
                'context': {
                    'default_product_id': self.product_id.id,
                    'default_product_uom_id': self.product_id.uom_id.id,
                    'default_scrap_qty': self.quantity,
                    'default_location_id': self.source_location_id.id,
                    'default_origin': 'FM-DISPOSITION-%s' % self.id,
                }}

    def action_open_receipt_for_return(self):
        self.ensure_one()
        self._manager()
        if self.state != 'approved' or self.resolution != 'return':
            raise UserError('Phương án hoàn trả chưa được duyệt.')
        if not self.receipt_picking_id:
            raise UserError('Chưa có phiếu nhận gốc để Return.')
        return {'type': 'ir.actions.act_window', 'name': 'Phiếu nhận gốc - dùng Return',
                'res_model': 'stock.picking', 'view_mode': 'form',
                'res_id': self.receipt_picking_id.id}

    def action_close(self):
        self.ensure_one()
        self._manager()
        if self.state != 'approved':
            raise UserError('Hồ sơ chưa được duyệt.')
        if self.resolution == 'quarantine':
            if not self.quarantine_picking_id or self.quarantine_picking_id.state != 'done':
                raise UserError('Phiếu chuyển vào HH phải hoàn thành trước khi đóng hồ sơ.')
        elif self.resolution == 'scrap':
            if not self.scrap_id or self.scrap_id.state != 'done':
                raise UserError('Cần liên kết phiếu Scrap đã Validate để đóng hồ sơ.')
            if self.scrap_id.product_id != self.product_id:
                raise UserError('Phiếu Scrap không khớp sản phẩm.')
            if self.scrap_id.location_id != self.source_location_id:
                raise UserError('Nguồn xuất hủy không khớp vị trí hàng được duyệt.')
            if abs(self.scrap_id.scrap_qty - self.quantity) > self.product_id.uom_id.rounding / 2:
                raise UserError('Số lượng Scrap không trùng số lượng được duyệt.')
        else:
            if not self.return_picking_id or self.return_picking_id.state != 'done':
                raise UserError('Cần liên kết phiếu hoàn trả đã hoàn thành.')
            if self.return_picking_id.location_dest_id.usage != 'supplier':
                raise UserError('Phiếu liên kết chưa phải giao dịch hoàn trả tới nhà cung cấp.')
            if not any(
                m.product_id == self.product_id and m.quantity >= self.quantity
                for m in self.return_picking_id.move_ids
            ):
                raise UserError('Phiếu hoàn trả không có đủ số lượng của sản phẩm được duyệt.')
        self.state = 'closed'

    def write(self, vals):
        if 'state' in vals and vals['state'] in ('approved', 'closed') and not self.env.user.has_group('stock.group_stock_manager'):
            raise UserError('Chỉ quản lý Inventory được phê duyệt hoặc đóng hồ sơ.')
        protected = {'issue_type', 'resolution', 'product_id', 'quantity',
                     'source_location_id', 'hold_location_id', 'receipt_picking_id', 'note'}
        if protected.intersection(vals) and any(r.state in ('submitted', 'approved', 'closed') for r in self):
            raise UserError('Không sửa nội dung hồ sơ đã gửi duyệt.')
        return super().write(vals)
