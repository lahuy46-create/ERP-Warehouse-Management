from collections import defaultdict

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero

from ..utils import normalize_name


# ==========================================================
# MODEL 1: DOT NHAP DU LIEU BAN HANG
# ==========================================================

class FmSalesBatch(models.Model):
    _name = 'fm.sales.batch'
    _description = 'FamilyMart - Dot nhap du lieu ban hang'
    _order = 'id desc'

    name = fields.Char(
        string='Tên lần nhập',
        required=True
    )

    period_start = fields.Date(
        string='Từ ngày',
        required=True
    )

    period_end = fields.Date(
        string='Đến ngày',
        required=True
    )

    file_sha256 = fields.Char(
        string='Mã kiểm tra file SHA256',
        readonly=True,
        index=True
    )

    _unique_import = models.Constraint(
        'UNIQUE (file_sha256, period_start, period_end)',
        'File bán hàng đã được nhập cho kỳ này.'
    )

    filename = fields.Char(
        string='Tên file',
        readonly=True
    )

    line_ids = fields.One2many(
        'fm.sales.record',
        'batch_id',
        string='Dòng bán hàng'
    )

    state = fields.Selection(
        [
            ('draft', 'Chờ đối chiếu'),
            ('done', 'Đã ghi nhận vào kho')
        ],
        default='draft',
        readonly=True
    )

    confirm_not_already_recorded = fields.Boolean(
        string='Xác nhận doanh số chưa trừ trong Odoo',
        default=False,
        help=(
            'Chỉ xác nhận khi doanh số trong file '
            'chưa được phản ánh vào tồn kho Odoo.'
        )
    )

    sale_count = fields.Integer(
        string='Số dòng',
        compute='_compute_count'
    )

    # ------------------------------------------------------
    # DEM DONG BAN HANG
    # ------------------------------------------------------

    @api.depends('line_ids')
    def _compute_count(self):
        for batch in self:
            batch.sale_count = len(batch.line_ids)

    # ------------------------------------------------------
    # KIEM TRA THOI GIAN BAN HANG
    # ------------------------------------------------------

    @api.constrains('period_start', 'period_end')
    def _check_period(self):
        for batch in self:
            if (
                batch.period_start
                and batch.period_end
                and batch.period_start > batch.period_end
            ):
                raise UserError(
                    'Từ ngày phải trước hoặc bằng Đến ngày.'
                )

    # ------------------------------------------------------
    # TIM VI TRI THEO THU TU UU TIEN
    #
    # 1. TB - Ke trung bay
    # 2. KT - Kho thuong
    # 3. KL - Kho lanh
    #
    # KHONG lay hang tai khu HH.
    # ------------------------------------------------------

    def _get_priority_locations(self):
        self.ensure_one()

        Location = self.env['stock.location']

        priority_roots = [
            ('TB', 'WH/Stock/TB'),
            ('KT', 'WH/Stock/KT'),
            ('KL', 'WH/Stock/KL'),
        ]

        result = Location.browse()
        company_id = self.env.company.id

        for code, path in priority_roots:

            roots = Location.search([
                ('complete_name', '=', path),
                ('usage', '=', 'internal'),
                ('company_id', 'in', [False, company_id]),
            ])

            if len(roots) != 1:
                raise UserError(
                    'Không tìm thấy duy nhất vị trí %s. '
                    'Hãy kiểm tra cấu trúc kho trong Inventory.'
                    % path
                )

            root = roots[0]

            locations = Location.search([
                ('id', 'child_of', root.id),
                ('usage', '=', 'internal'),
                ('company_id', 'in', [False, company_id]),
            ])

            if code == 'TB':
                # Uu tien cac ke con.
                locations = locations.filtered(
                    lambda location: location.id != root.id
                )

            locations = locations.sorted(
                key=lambda location: (
                    location.id != root.id
                    if code != 'TB' else False,
                    location.complete_name or '',
                    location.id,
                )
            )

            result |= locations

        if not result:
            raise UserError(
                'Không có vị trí xuất hàng hợp lệ.'
            )

        return result

    # ------------------------------------------------------
    # LAY TON KHO KHA DUNG
    # ------------------------------------------------------

    def _get_available_stock(self, product_ids, locations):
        self.ensure_one()

        quants = self.env['stock.quant'].sudo().search([
            ('product_id', 'in', product_ids),
            ('location_id', 'in', locations.ids),
            ('company_id', 'in', [
                False,
                self.env.company.id
            ]),
            ('owner_id', '=', False),
        ])

        available = defaultdict(float)

        for quant in quants:

            qty = (
                quant.quantity
                - quant.reserved_quantity
            )

            if qty <= 0:
                continue

            key = (
                quant.product_id.id,
                quant.location_id.id
            )

            available[key] += qty

        return available

    # ------------------------------------------------------
    # KIEM TRA DU LIEU TRUOC KHI TRU KHO
    # ------------------------------------------------------

    def _validate_sale_lines(self):
        self.ensure_one()

        if not self.line_ids:
            raise UserError(
                'Lần nhập chưa có dữ liệu bán hàng.'
            )

        for line in self.line_ids:

            if (
                line.state != 'draft'
                or line.stock_move_id
                or line.stock_move_ids
            ):
                raise UserError(
                    'Có dòng bán hàng đã được ghi nhận trước đó.'
                )

            product = line.product_id

            if line.match_status != 'matched' or not product:
                raise UserError(
                    'Barcode hoặc tên sản phẩm không khớp: %s'
                    % line.product_name
                )

            if (
                normalize_name(line.product_name)
                != normalize_name(product.name)
            ):
                raise UserError(
                    'Tên sản phẩm không khớp Inventory: %s'
                    % line.product_name
                )

            if (
                (line.barcode or '').strip()
                != (product.barcode or '').strip()
            ):
                raise UserError(
                    'Barcode không khớp Inventory: %s'
                    % line.product_name
                )

            if (
                not product.is_storable
                or product.tracking != 'none'
            ):
                raise UserError(
                    'Chỉ hỗ trợ sản phẩm By Quantity: %s'
                    % product.display_name
                )

            if (
                product.company_id
                and product.company_id != self.env.company
            ):
                raise UserError(
                    'Sản phẩm thuộc công ty khác: %s'
                    % product.display_name
                )

            rounding = product.uom_id.rounding

            if (
                line.quantity <= 0
                or float_is_zero(
                    line.quantity,
                    precision_rounding=rounding
                )
            ):
                raise UserError(
                    'Số lượng bán không hợp lệ: %s'
                    % product.display_name
                )

    # ------------------------------------------------------
    # TU DONG PHAN BO SO LUONG BAN
    #
    # Vi du:
    # Ban 10 san pham
    # TB-01 co 3
    # TB-02 co 4
    # KT co 20
    #
    # Ket qua:
    # TB-01 tru 3
    # TB-02 tru 4
    # KT tru 3
    # ------------------------------------------------------

    def _prepare_allocation_plan(self):
        self.ensure_one()

        locations = self._get_priority_locations()

        lines = self.line_ids.sorted(
            key=lambda line: line.id
        )

        product_ids = lines.mapped('product_id').ids

        available = self._get_available_stock(
            product_ids,
            locations
        )

        plan = []

        for line in lines:

            product = line.product_id
            rounding = product.uom_id.rounding
            remaining = line.quantity

            allocations = []

            for location in locations:

                if float_compare(
                    remaining,
                    0.0,
                    precision_rounding=rounding
                ) <= 0:
                    break

                key = (
                    product.id,
                    location.id
                )

                in_stock = max(
                    0.0,
                    available.get(key, 0.0)
                )

                if float_compare(
                    in_stock,
                    0.0,
                    precision_rounding=rounding
                ) <= 0:
                    continue

                take = min(
                    remaining,
                    in_stock
                )

                allocations.append({
                    'location_id': location.id,
                    'quantity': take,
                })

                # Tru trong bo nho phan bo.
                # Khong sua truc tiep stock.quant.
                available[key] = max(
                    0.0,
                    in_stock - take
                )

                remaining -= take

            if float_compare(
                remaining,
                0.0,
                precision_rounding=rounding
            ) > 0:
                raise UserError(
                    'Không đủ tồn kho cho %s.\n'
                    'Số lượng còn thiếu: %.2f.'
                    % (
                        product.display_name,
                        remaining
                    )
                )

            plan.append({
                'line': line,
                'allocations': allocations,
            })

        return plan

    # ------------------------------------------------------
    # TAO GIAO DICH XUAT BAN ODOO 19
    #
    # DA SUA LOI:
    # Invalid field 'name' in 'stock.move'
    # ------------------------------------------------------

    def _create_sale_move(
        self,
        line,
        source_location,
        quantity
    ):
        self.ensure_one()

        product = line.product_id

        customer_location = self.env.ref(
            'stock.stock_location_customers'
        )

        # Odoo 19: khong truyen field 'name'.
        move = self.env['stock.move'].create({
            'origin': 'FM-SALES-BATCH-%s' % self.id,
            'product_id': product.id,
            'product_uom_qty': quantity,
            'product_uom': product.uom_id.id,
            'location_id': source_location.id,
            'location_dest_id': customer_location.id,
            'company_id': self.env.company.id,
        })

        # Xac nhan stock move.
        move._action_confirm(merge=False)

        # Du tru so luong tu vi tri nguon.
        move._action_assign()

        rounding = product.uom_id.rounding

        if float_compare(
            move.quantity,
            quantity,
            precision_rounding=rounding
        ) < 0:
            raise UserError(
                'Không đủ hàng được dự trữ cho %s '
                'tại %s. Cần %.2f, dự trữ được %.2f.'
                % (
                    product.display_name,
                    source_location.display_name,
                    quantity,
                    move.quantity,
                )
            )

        # Danh dau hang da duoc lay.
        move.picked = True

        # Hoan tat xuat ban va cap nhat stock.quant.
        move._action_done()

        if move.state != 'done':
            raise UserError(
                'Không thể hoàn tất xuất bán %s.'
                % product.display_name
            )

        return move

    # ------------------------------------------------------
    # GHI NHAN DOANH SO VA TRU TON KHO
    # ------------------------------------------------------

    def action_post(self):
        self.ensure_one()

        if not self.env.user.has_group(
            'stock.group_stock_manager'
        ):
            raise UserError(
                'Chỉ quản lý Inventory được ghi nhận doanh số.'
            )

        if self.state != 'draft':
            raise UserError(
                'Lô bán hàng đã được ghi nhận trước đó.'
            )

        if not self.confirm_not_already_recorded:
            raise UserError(
                'Hãy xác nhận doanh số chưa được '
                'phản ánh trong Inventory.'
            )

        # Buoc 1: Kiem tra cac dong ban hang.
        self._validate_sale_lines()

        # Buoc 2: Lap ke hoach tru kho.
        plan = self._prepare_allocation_plan()

        Location = self.env['stock.location']
        Move = self.env['stock.move']

        # Buoc 3: Tao stock move tu cac vi tri da phan bo.
        for item in plan:

            line = item['line']
            created_moves = Move.browse()

            for allocation in item['allocations']:

                source = Location.browse(
                    allocation['location_id']
                )

                move = self._create_sale_move(
                    line=line,
                    source_location=source,
                    quantity=allocation['quantity']
                )

                created_moves |= move

            if not created_moves:
                raise UserError(
                    'Không tạo được giao dịch cho %s.'
                    % line.product_name
                )

            # Luu danh sach giao dich da tao.
            line.write({
                'stock_move_id': created_moves[0].id,
                'stock_move_ids': [
                    (6, 0, created_moves.ids)
                ],
                'state': 'done'
            })

        # Buoc 4: Danh dau lo da hoan tat.
        self.write({
            'state': 'done'
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'reload'
        }

    # ------------------------------------------------------
    # BAO VE DU LIEU LO BAN HANG
    # ------------------------------------------------------

    def write(self, vals):

        protected = {
            'period_start',
            'period_end',
            'file_sha256',
            'line_ids',
            'confirm_not_already_recorded'
        }

        if protected.intersection(vals):
            if any(batch.state == 'done' for batch in self):
                raise UserError(
                    'Không thể sửa lô bán hàng đã ghi nhận.'
                )

        return super().write(vals)

    def unlink(self):

        if any(batch.state == 'done' for batch in self):
            raise UserError(
                'Không được xóa lô bán hàng đã ghi nhận. '
                'Hãy dùng nghiệp vụ trả hàng trong Inventory.'
            )

        return super().unlink()


# ==========================================================
# MODEL 2: CHI TIET DONG BAN HANG
# ==========================================================

class FamilyMartSalesRecord(models.Model):
    _name = 'fm.sales.record'
    _description = 'FamilyMart - Dong du lieu ban hang'
    _rec_name = 'product_name'

    batch_id = fields.Many2one(
        'fm.sales.batch',
        string='Lần nhập',
        ondelete='restrict'
    )

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

    product_id = fields.Many2one(
        'product.product',
        string='Sản phẩm trong Inventory',
        compute='_compute_match',
        store=True
    )

    match_status = fields.Selection(
        [
            ('matched', 'Đã liên kết'),
            ('not_found', 'Không tìm thấy barcode'),
            ('name_mismatch', 'Tên sản phẩm không khớp'),
            ('ambiguous', 'Barcode bị trùng')
        ],
        string='Đối chiếu',
        compute='_compute_match',
        store=True
    )

    # Giu truong cu de tuong thich database.
    # Nguoi dung khong can chon ke xuat ban.
    sale_location_id = fields.Many2one(
        'stock.location',
        string='Kệ xuất bán (dữ liệu cũ)',
        domain=[('usage', '=', 'internal')]
    )

    # Giao dich kho dau tien.
    stock_move_id = fields.Many2one(
        'stock.move',
        string='Giao dịch kho đầu tiên',
        readonly=True,
        copy=False
    )

    # Tat ca giao dich kho cua dong ban hang.
    stock_move_ids = fields.Many2many(
        'stock.move',
        'fm_sales_record_move_rel',
        'sale_record_id',
        'move_id',
        string='Các giao dịch xuất bán',
        readonly=True,
        copy=False
    )

    state = fields.Selection(
        [
            ('draft', 'Chưa trừ kho'),
            ('done', 'Đã trừ tồn kho')
        ],
        default='draft',
        readonly=True,
        copy=False
    )

    _quantity_positive = models.Constraint(
        'CHECK (quantity > 0)',
        'Số lượng bán phải lớn hơn 0.'
    )

    # ------------------------------------------------------
    # DOI CHIEU BARCODE VA TEN SAN PHAM
    # ------------------------------------------------------

    @api.depends('barcode', 'product_name')
    def _compute_match(self):

        Product = self.env['product.product'].sudo()

        for record in self:

            record.product_id = False
            record.match_status = 'not_found'

            barcode = (record.barcode or '').strip()

            if not barcode:
                continue

            products = Product.search([
                ('barcode', '=', barcode)
            ], limit=2)

            if not products:
                continue

            if len(products) > 1:
                record.match_status = 'ambiguous'
                continue

            product = products[0]

            if (
                normalize_name(product.name)
                != normalize_name(record.product_name)
            ):
                record.match_status = 'name_mismatch'
                continue

            record.product_id = product.id
            record.match_status = 'matched'

    # ------------------------------------------------------
    # KHONG CHO SUA DONG DA GHI NHAN
    # ------------------------------------------------------

    def write(self, vals):

        protected = {
            'barcode',
            'product_name',
            'quantity',
            'sale_location_id',
            'batch_id',
        }

        if protected.intersection(vals):
            if any(record.state == 'done' for record in self):
                raise UserError(
                    'Không thể sửa dữ liệu đã trừ tồn kho.'
                )

        return super().write(vals)

    def unlink(self):

        if any(record.state == 'done' for record in self):
            raise UserError(
                'Không thể xóa dòng bán hàng đã ghi nhận.'
            )

        return super().unlink()
