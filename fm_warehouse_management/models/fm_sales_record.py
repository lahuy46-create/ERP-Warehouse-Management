from odoo import models, fields


class FamilyMartSalesRecord(models.Model):
    _name = 'fm.sales.record'
    _description = 'Du lieu ban hang FamilyMart'
    _rec_name = 'product_name'

    barcode = fields.Char(
        string='Mã barcode',
        required=True,
        index=True
    )

    product_name = fields.Char(
        string='Sản phẩm',
        required=True
    )

    quantity = fields.Float(
        string='Số lượng bán',
        required=True,
        digits='Product Unit of Measure'
    )

    _quantity_positive = models.Constraint(
        'CHECK (quantity > 0)',
        'Số lượng bán phải lớn hơn 0.'
    )
