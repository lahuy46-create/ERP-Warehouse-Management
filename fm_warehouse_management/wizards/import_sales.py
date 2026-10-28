import base64
import csv
import hashlib
import io
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from odoo import fields, models
from odoo.exceptions import UserError
from ..utils import normalize_column


class FamilyMartSalesImportWizard(models.TransientModel):
    _name = 'fm.sales.import.wizard'
    _description = 'FamilyMart - Import 3 cot ban hang CSV'

    csv_file = fields.Binary(string='File CSV UTF-8', required=True)
    filename = fields.Char(string='Tên tệp')
    period_start = fields.Date(string='Kỳ bán từ ngày', required=True)
    period_end = fields.Date(string='Kỳ bán đến ngày', required=True)

    def action_import(self):
        self.ensure_one()
        if not self.env.user.has_group('stock.group_stock_manager'):
            raise UserError('Chỉ quản lý Inventory được nhập dữ liệu bán hàng.')
        if self.period_start > self.period_end:
            raise UserError('Từ ngày không được sau Đến ngày.')
        if not self.filename or not self.filename.lower().endswith('.csv'):
            raise UserError('Chỉ hỗ trợ file .csv UTF-8 ở phiên bản này.')
        raw = base64.b64decode(self.csv_file)
        if len(raw) > 5 * 1024 * 1024:
            raise UserError('File lớn hơn 5 MB. Hãy chia thành các kỳ nhập nhỏ.')
        try:
            content = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            raise UserError('Hãy lưu file CSV theo mã hóa UTF-8.')
        try:
            dialect = csv.Sniffer().sniff(content[:4096], delimiters=',;\t')
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(content, newline=''), dialect=dialect)
        if not reader.fieldnames:
            raise UserError('Không tìm thấy dòng tiêu đề trong CSV.')
        columns = {normalize_column(name): name for name in reader.fieldnames}
        def find_one(names):
            return next((columns[n] for n in names if n in columns), None)
        barcode_col = find_one(('mabarcode', 'barcode', 'mavach'))
        name_col = find_one(('sanpham', 'tensanpham', 'product', 'productname'))
        qty_col = find_one(('soluong', 'soluongban', 'quantity', 'qty'))
        if not all((barcode_col, name_col, qty_col)):
            raise UserError('CSV cần đúng ba cột: Mã barcode, Sản phẩm, Số lượng.')
        rows = []
        for number, item in enumerate(reader, 2):
            if not any((value or '').strip() for value in item.values() if isinstance(value, str)):
                continue
            barcode = (item.get(barcode_col) or '').strip()
            name = (item.get(name_col) or '').strip()
            value = (item.get(qty_col) or '').strip().replace(' ', '')
            if not barcode or not name:
                raise UserError('Dòng %s: thiếu barcode hoặc tên sản phẩm.' % number)
            try:
                if ',' in value and '.' not in value:
                    value = value.replace(',', '.')
                quantity = Decimal(value)
            except (InvalidOperation, ValueError):
                raise UserError('Dòng %s: số lượng không hợp lệ.' % number)
            if not quantity.is_finite() or quantity <= 0:
                raise UserError('Dòng %s: số lượng phải lớn hơn 0.' % number)
            rows.append((barcode, name, float(quantity)))
        if not rows:
            raise UserError('File CSV chưa có dòng bán hàng.')
        # Same file, same period should not be posted as new sales twice.
        digest = hashlib.sha256(raw).hexdigest()
        exists = self.env['fm.sales.batch'].search([
            ('file_sha256', '=', digest),
            ('period_start', '=', self.period_start),
            ('period_end', '=', self.period_end),
        ], limit=1)
        if exists:
            raise UserError('File đã được nhập trong kỳ này: %s. Không nhập lại để tránh trừ tồn trùng.' % exists.display_name)
        # Aggregate repeated product rows; still require one explicit shelf per product on posting.
        aggregate = defaultdict(float)
        for barcode, name, quantity in rows:
            aggregate[(barcode, name)] += quantity
        batch = self.env['fm.sales.batch'].create({
            'name': '%s (%s → %s)' % (self.filename, self.period_start, self.period_end),
            'filename': self.filename,
            'period_start': self.period_start,
            'period_end': self.period_end,
            'file_sha256': digest,
        })
        self.env['fm.sales.record'].create([{
            'batch_id': batch.id, 'barcode': barcode,
            'product_name': name, 'quantity': quantity,
        } for (barcode, name), quantity in aggregate.items()])
        return {'type': 'ir.actions.act_window', 'res_model': 'fm.sales.batch',
                'res_id': batch.id, 'view_mode': 'form', 'target': 'current'}
