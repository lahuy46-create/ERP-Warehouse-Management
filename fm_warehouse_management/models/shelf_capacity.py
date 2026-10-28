from odoo import api, fields, models
from odoo.exceptions import UserError
from ..utils import replenish_quantity


class ShelfCapacity(models.Model):
    _name = 'fm.shelf.capacity'
    _description = 'FamilyMart - Suc chua va de xuat cham hang'
    _rec_name = 'product_id'

    product_id = fields.Many2one('product.product', string='Sản phẩm', required=True, ondelete='restrict')
    location_id = fields.Many2one('stock.location', string='Kệ trưng bày', required=True, ondelete='restrict', domain=[('usage', '=', 'internal')])
    capacity = fields.Integer(string='Sức chứa tối đa', required=True, default=1)
    source_location_id = fields.Many2one('stock.location', string='Kho cấp hàng (KT/KL)', domain=[('usage', '=', 'internal')])
    shelf_qty = fields.Float(string='Tồn trên kệ', compute='_compute_replenishment', digits='Product Unit of Measure')
    source_available_qty = fields.Float(string='Kho khả dụng', compute='_compute_replenishment', digits='Product Unit of Measure')
    suggested_qty = fields.Float(string='Đề xuất châm', compute='_compute_replenishment', digits='Product Unit of Measure')
    low_shelf = fields.Boolean(string='Dưới 30%', compute='_compute_replenishment')
    replenishment_picking_id = fields.Many2one('stock.picking', string='Phiếu châm gần nhất', readonly=True, copy=False)

    _capacity_positive = models.Constraint('CHECK (capacity > 0)', 'Sức chứa phải lớn hơn 0.')
    _unique_product_location = models.Constraint('UNIQUE (product_id, location_id)', 'Sản phẩm đã được cấu hình tại kệ này.')

    @api.depends('product_id', 'location_id', 'capacity', 'source_location_id')
    def _compute_replenishment(self):
        Quant = self.env['stock.quant'].sudo()
        for rec in self:
            rec.shelf_qty = 0.0
            rec.source_available_qty = 0.0
            rec.suggested_qty = 0.0
            rec.low_shelf = False
            if not rec.product_id or not rec.location_id:
                continue
            shelf_quants = Quant.search([
                ('product_id', '=', rec.product_id.id),
                ('location_id', 'child_of', rec.location_id.id),
                ('company_id', 'in', [False, self.env.company.id]),
            ])
            rec.shelf_qty = sum(shelf_quants.mapped('quantity'))
            rec.low_shelf = rec.capacity > 0 and rec.shelf_qty < rec.capacity * 0.30
            source = rec.source_location_id
            if not source or source == rec.location_id:
                continue
            # Prevent selecting an ancestor of the shelf (would include display stock).
            if rec.location_id.id in source.ids or f'{source.id}/' in (rec.location_id.parent_path or ''):
                continue
            if f'{rec.location_id.id}/' in (source.parent_path or ''):
                continue
            quants = Quant.search([
                ('product_id', '=', rec.product_id.id),
                ('location_id', 'child_of', source.id),
                ('company_id', 'in', [False, self.env.company.id]),
            ])
            rec.source_available_qty = max(0.0, sum(q.quantity - q.reserved_quantity for q in quants))
            rec.suggested_qty = replenish_quantity(rec.capacity, rec.shelf_qty, rec.source_available_qty)

    def action_create_replenishment(self):
        self.ensure_one()
        if not self.env.user.has_group('stock.group_stock_manager'):
            raise UserError('Chỉ quản lý Inventory được tạo phiếu châm hàng.')
        if not self.source_location_id:
            raise UserError('Chưa chọn kho cấp hàng KT/KL.')
        if self.source_location_id.usage != 'internal' or self.location_id.usage != 'internal':
            raise UserError('Vị trí nguồn và kệ phải là vị trí nội bộ.')
        if self.source_location_id == self.location_id or f'{self.source_location_id.id}/' in (self.location_id.parent_path or '') or f'{self.location_id.id}/' in (self.source_location_id.parent_path or ''):
            raise UserError('Kho cấp hàng và kệ trưng bày không được chồng lấn.')
        old = self.replenishment_picking_id
        if old and old.state not in ('done', 'cancel'):
            raise UserError('Đã tồn tại phiếu châm chưa hoàn tất: %s' % old.display_name)
        qty = self.suggested_qty
        if qty <= 0:
            raise UserError('Không có số lượng cần châm hoặc kho cấp hàng không đủ hàng.')
        # Restrict to a single company; manager validates movement in standard Inventory.
        operation = self.env['stock.picking.type'].search([
            ('code', '=', 'internal'),
            ('company_id', 'in', [False, self.env.company.id]),
        ], limit=1)
        if not operation:
            raise UserError('Chưa có loại phiếu Internal Transfers trong Inventory.')
        picking = self.env['stock.picking'].create({
            'picking_type_id': operation.id,
            'origin': 'FM-REPLENISH-%s' % self.id,
            'location_id': self.source_location_id.id,
            'location_dest_id': self.location_id.id,
            'move_ids': [(0, 0, {
                'name': 'Châm kệ: %s' % self.product_id.display_name,
                'product_id': self.product_id.id,
                'product_uom_qty': qty,
                'product_uom': self.product_id.uom_id.id,
                'location_id': self.source_location_id.id,
                'location_dest_id': self.location_id.id,
            })],
        })
        self.replenishment_picking_id = picking.id
        return {'type': 'ir.actions.act_window', 'name': 'Phiếu châm hàng (bản nháp)',
                'res_model': 'stock.picking', 'view_mode': 'form', 'res_id': picking.id}
