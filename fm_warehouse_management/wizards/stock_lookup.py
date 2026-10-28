from odoo import api, fields, models


class FamilyMartStockLookup(models.TransientModel):
    _name = 'fm.stock.lookup.wizard'
    _description = 'FamilyMart - Tra cuu ton kho theo san pham va vi tri'

    product_id = fields.Many2one('product.product', string='Sản phẩm', required=True)
    location_id = fields.Many2one('stock.location', string='Khu/kệ', domain=[('usage', '=', 'internal')], required=True)
    qty_on_hand = fields.Float(string='Tồn thực tế', compute='_compute_qty')
    qty_available = fields.Float(string='Tồn khả dụng', compute='_compute_qty')

    @api.depends('product_id', 'location_id')
    def _compute_qty(self):
        Quant = self.env['stock.quant'].sudo()
        for rec in self:
            rec.qty_on_hand = 0.0
            rec.qty_available = 0.0
            if not rec.product_id or not rec.location_id:
                continue
            quants = Quant.search([
                ('product_id', '=', rec.product_id.id),
                ('location_id', 'child_of', rec.location_id.id),
                ('company_id', 'in', [False, self.env.company.id]),
            ])
            rec.qty_on_hand = sum(quants.mapped('quantity'))
            rec.qty_available = sum(q.quantity - q.reserved_quantity for q in quants)
