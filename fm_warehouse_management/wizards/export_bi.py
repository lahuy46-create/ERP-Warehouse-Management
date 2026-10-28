import base64
import csv
import io
import zipfile
from odoo import fields, models
from odoo.exceptions import UserError


class FamilyMartBIExportWizard(models.TransientModel):
    _name = 'fm.bi.export.wizard'
    _description = 'FamilyMart - Xuat bao cao CSV cho Power BI'

    file_data = fields.Binary(string='Tệp dữ liệu ZIP', readonly=True)
    file_name = fields.Char(string='Tên tệp', readonly=True)

    @staticmethod
    def _csv(rows):
        buffer = io.StringIO(newline='')
        writer = csv.writer(buffer)
        writer.writerows(rows)
        return buffer.getvalue().encode('utf-8-sig')

    def action_export(self):
        self.ensure_one()
        if not self.env.user.has_group('stock.group_stock_manager'):
            raise UserError('Chỉ quản lý Inventory được xuất dữ liệu BI.')
        cap_rows = [['product_barcode', 'product_name', 'shelf_location', 'capacity', 'shelf_on_hand',
                     'backstock_available', 'suggested_qty', 'low_30_percent']]
        for rec in self.env['fm.shelf.capacity'].search([]):
            cap_rows.append([rec.product_id.barcode or '', rec.product_id.display_name,
                rec.location_id.complete_name, rec.capacity, rec.shelf_qty,
                rec.source_available_qty, rec.suggested_qty, int(rec.low_shelf)])
        sale_rows = [['batch', 'period_start', 'period_end', 'barcode', 'product', 'qty', 'match_status', 'state', 'shelf']]
        for rec in self.env['fm.sales.record'].search([]):
            sale_rows.append([rec.batch_id.name or '', str(rec.batch_id.period_start or ''), str(rec.batch_id.period_end or ''),
                rec.barcode, rec.product_name, rec.quantity, rec.match_status, rec.state,
                rec.sale_location_id.complete_name or ''])
        expiry_rows = [['barcode', 'product', 'location', 'expiry_date', 'days_left', 'alert', 'qty_observed', 'state']]
        for rec in self.env['fm.expiry.record'].search([]):
            expiry_rows.append([rec.product_id.barcode or '', rec.product_id.display_name,
                rec.location_id.complete_name, str(rec.expiry_date), rec.days_left,
                rec.alert_level, rec.quantity_observed, rec.state])
        issue_rows = [['type', 'title', 'barcode', 'product', 'location', 'qty', 'status', 'notes']]
        for rec in self.env['fm.issue.record'].search([]):
            issue_rows.append([rec.issue_type, rec.name, rec.product_id.barcode or '',
                rec.product_id.display_name or '', rec.location_id.complete_name or '',
                rec.quantity, rec.state, rec.note or ''])
        stock_rows = [['barcode', 'product', 'location', 'on_hand', 'reserved', 'available']]
        Quant = self.env['stock.quant'].sudo()
        quants = Quant.search([('location_id.usage', '=', 'internal'),
                               ('company_id', 'in', [False, self.env.company.id])])
        for quant in quants:
            stock_rows.append([quant.product_id.barcode or '', quant.product_id.display_name,
                quant.location_id.complete_name, quant.quantity, quant.reserved_quantity,
                quant.quantity - quant.reserved_quantity])
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, rows in [
                ('shelves.csv', cap_rows), ('sales.csv', sale_rows),
                ('expiry_manual.csv', expiry_rows), ('issues.csv', issue_rows),
                ('stock_quants.csv', stock_rows),
            ]:
                archive.writestr(name, self._csv(rows))
            archive.writestr('README.txt',
                'FamilyMart BI - CSV UTF-8. Expiry observations are NOT synced to stock lots. '
                'Refresh manually after inventory movements. Exclude HH location from sellable inventory.\n')
        self.write({'file_data': base64.b64encode(buffer.getvalue()),
                    'file_name': 'familymart_powerbi_export.zip'})
        return {'type': 'ir.actions.act_window', 'res_model': self._name,
                'res_id': self.id, 'view_mode': 'form', 'target': 'new'}
