from odoo import fields, models


class FamilyMartHome(models.Model):
    _name = 'fm.home'
    _description = 'FamilyMart - Trang chu dieu huong'

    name = fields.Char(string='Tên trang chủ', required=True)
