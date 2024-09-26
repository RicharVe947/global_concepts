from odoo import api, models, fields


class AccountGlobaLine(models.Model):
    _name = "account.global.line"
    _description = "Account Global Lines"

    move_id = fields.Many2one('account.move', string='Journal Entry',
                              index=True, readonly=True, auto_join=True, ondelete="cascade",
                              check_company=True,
                              help="The move of this entry line.")
    company_id = fields.Many2one(related='move_id.company_id', store=True, readonly=True, )
    product_id = fields.Many2one('product.product', string='Product', ondelete='restrict')
    quantity = fields.Float(string='Quantity',
                            default=1.0,
                            digits='Product Unit of Measure',
                            help="The optional quantity expressed by this line, eg: number of product sold. "
                                 "The quantity is not a legal requirement but is very useful for some reports.")

    product_uom_id = fields.Many2one('uom.uom', string='Unit of Measure',
                                     domain="[('category_id', '=', product_uom_category_id)]", ondelete="restrict")
    product_uom_category_id = fields.Many2one('uom.category', related='product_id.uom_id.category_id')
    price_unit = fields.Float(string='Unit Price', digits='Product Price')

    price_subtotal = fields.Monetary(string='Subtotal', store=True, readonly=True,
                                     currency_field='currency_id')
    price_total = fields.Monetary(string='Total', store=True, readonly=True,
                                  currency_field='currency_id')
    tax_ids = fields.Many2many(
        comodel_name='account.tax',
        string="Taxes",
        context={'active_test': False},
        check_company=True,
        help="Taxes that apply on the base amount")
    currency_id = fields.Many2one('res.currency', string='Currency', related="move_id.currency_id")
    discount = fields.Float(string='Discount (%)', digits='Discount', default=0.0)
    name = fields.Char(string='Label', related="product_id.display_name", store=True, readonly=False)
    l10n_mx_edi_customs_number = fields.Char(
        help='Optional field for entering the customs information in the case '
        'of first-hand sales of imported goods or in the case of foreign trade'
        ' operations with goods or services.\n'
        'The format must be:\n'
        ' - 2 digits of the year of validation followed by two spaces.\n'
        ' - 2 digits of customs clearance followed by two spaces.\n'
        ' - 4 digits of the serial number followed by two spaces.\n'
        ' - 1 digit corresponding to the last digit of the current year, '
        'except in case of a consolidated customs initiated in the previous '
        'year of the original request for a rectification.\n'
        ' - 6 digits of the progressive numbering of the custom.',
        string='Customs number',
        copy=False)
    l10n_mx_edi_umt_aduana_id = fields.Many2one(
        comodel_name='uom.uom',
        string="UMT Aduana",
        readonly=True, store=True, compute_sudo=True,
        related='product_id.l10n_mx_edi_umt_aduana_id',
        help="Used in complement 'Comercio Exterior' to indicate in the products the TIGIE Units of Measurement. "
             "It is based in the SAT catalog.")
    l10n_mx_edi_qty_umt = fields.Float(
        string="Qty UMT",
        digits=(16, 3),
        readonly=False, store=True,
        compute='_compute_l10n_mx_edi_qty_umt',
        help="Quantity expressed in the UMT from product. It is used in the attribute 'CantidadAduana' in the CFDI")
    l10n_mx_edi_price_unit_umt = fields.Float(
        string="Unit Value UMT",
        readonly=True, store=True,
        compute='_compute_l10n_mx_edi_price_unit_umt',
        help="Unit value expressed in the UMT from product. It is used in the attribute 'ValorUnitarioAduana' in the "
             "CFDI")

    @api.depends('l10n_mx_edi_umt_aduana_id', 'product_uom_id', 'quantity')
    def _compute_l10n_mx_edi_qty_umt(self):
        for line in self:
            product_aduana_code = line.l10n_mx_edi_umt_aduana_id.l10n_mx_edi_code_aduana
            uom_aduana_code = line.product_uom_id.l10n_mx_edi_code_aduana
            if product_aduana_code == uom_aduana_code:
                line.l10n_mx_edi_qty_umt = line.quantity
            elif '01' in (product_aduana_code or ''):
                line.l10n_mx_edi_qty_umt = line.product_id.weight * line.quantity
            else:
                line.l10n_mx_edi_qty_umt = None

    @api.depends('quantity', 'price_unit', 'l10n_mx_edi_qty_umt')
    def _compute_l10n_mx_edi_price_unit_umt(self):
        for line in self:
            if line.l10n_mx_edi_qty_umt:
                line.l10n_mx_edi_price_unit_umt = line.quantity * line.price_unit / line.l10n_mx_edi_qty_umt
            else:
                line.l10n_mx_edi_price_unit_umt = line.l10n_mx_edi_price_unit_umt

    @api.onchange('product_id')
    def _onchange_product_id(self):
        for line in self:
            if not line.product_id:
                continue

            #line.name = line._get_computed_name()
            #line.account_id = line._get_computed_account()
            taxes = line._get_computed_taxes()
            if taxes and line.move_id.fiscal_position_id:
                taxes = line.move_id.fiscal_position_id.map_tax(taxes)
            line.tax_ids = taxes
            line.product_uom_id = line._get_computed_uom()
            line.price_unit = line._get_computed_price_unit()

    def _get_computed_taxes(self):
        self.ensure_one()
        tax_ids = None
        if self.move_id.is_sale_document(include_receipts=True):
            # Out invoice.
            if self.product_id.taxes_id:
                tax_ids = self.product_id.taxes_id.filtered(lambda tax: tax.company_id == self.move_id.company_id)
            if not tax_ids:
                tax_ids = self.move_id.company_id.account_sale_tax_id
        elif self.move_id.is_purchase_document(include_receipts=True):
            # In invoice.
            if self.product_id.supplier_taxes_id:
                tax_ids = self.product_id.supplier_taxes_id.filtered(lambda tax: tax.company_id == self.move_id.company_id)
            if not tax_ids:
                tax_ids = self.move_id.company_id.account_purchase_tax_id
        if self.company_id and tax_ids:
            tax_ids = tax_ids.filtered(lambda tax: tax.company_id == self.company_id)
        return tax_ids

    def _get_computed_uom(self):
        self.ensure_one()
        if self.move_id.is_purchase_document():
            return self.product_id.uom_po_id
        else:
            return self.product_id.uom_id

    def _get_computed_price_unit(self):
        ''' Helper to get the default price unit based on the product by taking care of the taxes
        set on the product and the fiscal position.
        :return: The price unit.
        '''
        self.ensure_one()

        if not self.product_id:
            return 0.0
        if self.move_id.is_sale_document(include_receipts=True):
            document_type = 'sale'
        elif self.move_id.is_purchase_document(include_receipts=True):
            document_type = 'purchase'
        else:
            document_type = 'other'

        return self.product_id._get_tax_included_unit_price(
            self.move_id.company_id,
            self.move_id.currency_id,
            self.move_id.date,
            document_type,
            fiscal_position=self.move_id.fiscal_position_id,
            product_uom=self.product_uom_id
        )

    @api.onchange('quantity', 'price_unit', 'tax_ids')
    def _onchange_price_subtotal(self):
        for line in self:
            if not line.move_id.is_invoice(include_receipts=True):
                continue

            line.update(line._get_price_total_and_subtotal())

    def _get_price_total_and_subtotal(self, price_unit=None, quantity=None, discount=None, currency=None, product=None, partner=None, taxes=None, move_type=None):
        self.ensure_one()
        return self._get_price_total_and_subtotal_model(
            price_unit=self.price_unit if price_unit is None else price_unit,
            quantity=self.quantity if quantity is None else quantity,
            discount=discount if discount else 0.0,
            currency=self.currency_id if currency is None else currency,
            product=self.product_id if product is None else product,
            partner=self.move_id.partner_id if partner is None else partner,
            taxes=self.tax_ids if taxes is None else taxes,
            move_type=self.move_id.move_type if move_type is None else move_type,
        )

    @api.model
    def _get_price_total_and_subtotal_model(self, price_unit, quantity, discount, currency, product, partner, taxes, move_type):
        ''' This method is used to compute 'price_total' & 'price_subtotal'.'''
        res = {}

        # Compute 'price_subtotal'.
        line_discount_price_unit = price_unit * (1 - (discount / 100.0))
        subtotal = quantity * line_discount_price_unit

        # Compute 'price_total'.
        if taxes:
            taxes_res = taxes._origin.with_context(force_sign=1).compute_all(line_discount_price_unit,
                quantity=quantity, currency=currency, product=product, partner=partner, is_refund=move_type in ('out_refund', 'in_refund'))
            res['price_subtotal'] = taxes_res['total_excluded']
            res['price_total'] = taxes_res['total_included']
        else:
            res['price_total'] = res['price_subtotal'] = subtotal
        #In case of multi currency, round before it's use for computing debit credit
        if currency:
            res = {k: currency.round(v) for k, v in res.items()}
        return res

    def _prepare_edi_vals_to_export(self):
        ''' The purpose of this helper is the same as '_prepare_edi_vals_to_export' but for a single invoice line.
        This includes the computation of the tax details for each invoice line or the management of the discount.
        Indeed, in some EDI, we need to provide extra values depending the discount such as:
        - the discount as an amount instead of a percentage.
        - the price_unit but after subtraction of the discount.

        :return: A python dict containing default pre-processed values.
        '''
        self.ensure_one()

        if self.discount == 100.0:
            gross_price_subtotal = self.currency_id.round(self.price_unit * self.quantity)
        else:
            gross_price_subtotal = self.currency_id.round(self.price_subtotal / (1 - self.discount / 100.0))

        res = {
            'line': self,
            'price_unit_after_discount': self.currency_id.round(self.price_unit * (1 - (self.discount / 100.0))),
            'price_subtotal_before_discount': gross_price_subtotal,
            'price_subtotal_unit': self.currency_id.round(self.price_subtotal / self.quantity) if self.quantity else 0.0,
            'price_total_unit': self.currency_id.round(self.price_total / self.quantity) if self.quantity else 0.0,
            'price_discount': gross_price_subtotal - self.price_subtotal,
            'price_discount_unit': (gross_price_subtotal - self.price_subtotal) / self.quantity if self.quantity else 0.0,
            'gross_price_total_unit': self.currency_id.round(gross_price_subtotal / self.quantity) if self.quantity else 0.0,
            'unece_uom_code': self.product_id.product_tmpl_id.uom_id._get_unece_code(),
            'tax_details_transferred_global': self.get_tax_detail_transferred_global(self.move_id),
            'tax_details_withholding_global': self.get_tax_detail_withholding_global(self.move_id)
        }
        return res

    def get_tax_detail_transferred_global(self, invoice):
        balance_multiplicator = -1 if invoice.is_inbound() else 1
        currency_rate_save = invoice.currency_id.rate_ids[0].inverse_company_rate
        total_tax_rate_transferred = 0.0
        for x in invoice.global_lines.mapped("tax_ids.amount"):
            if x >= 0:
                total_tax_rate_transferred += x
        values = {
            'base_amount_currency': self.price_subtotal * balance_multiplicator,
            'tax_amount_currency': self.price_subtotal * balance_multiplicator * (total_tax_rate_transferred/100),
            'base_amount': self.price_subtotal * balance_multiplicator * currency_rate_save,
            'tax_amount': self.price_subtotal * balance_multiplicator * (total_tax_rate_transferred/100) * currency_rate_save
        }
        tax_detail = []
        for tax_id in invoice.global_lines.mapped("tax_ids"):
            if tax_id.amount >= 0:
                line_val = {
                    'base_amount': self.price_subtotal * balance_multiplicator * currency_rate_save,
                    'tax_amount': self.price_subtotal * balance_multiplicator * (tax_id.amount/100) * currency_rate_save,
                    'base_amount_currency': self.price_subtotal * balance_multiplicator,
                    'tax_amount_currency': self.price_subtotal * balance_multiplicator * (tax_id.amount/100),
                    'tax': tax_id,
                    'exemption_reason': tax_id.name,
                    'tax_rate_transferred': tax_id.amount / 100,
                    'cfdi_name': self.get_tax_cfdi_name(tax_id)
                }
                tax_detail.append(line_val)
        values["tax_details"] = tax_detail
        return values

    def get_tax_detail_withholding_global(self, invoice):
        balance_multiplicator = -1 if invoice.is_inbound() else 1
        currency_rate_save = invoice.currency_id.rate_ids[0].inverse_company_rate
        total_tax_rate_transferred = 0.0
        for x in invoice.global_lines.mapped("tax_ids.amount"):
            if x < 0:
                total_tax_rate_transferred += x
        values = {
            'base_amount_currency': self.price_subtotal * balance_multiplicator,
            'tax_amount_currency': self.price_subtotal * balance_multiplicator * (total_tax_rate_transferred/100),
            'base_amount': self.price_subtotal * balance_multiplicator * currency_rate_save,
            'tax_amount': self.price_subtotal * balance_multiplicator * (total_tax_rate_transferred/100) * currency_rate_save
        }
        tax_detail = []
        for tax_id in invoice.global_lines.mapped("tax_ids"):
            if tax_id.amount < 0:
                line_val = {
                    'base_amount': self.price_subtotal * balance_multiplicator * currency_rate_save,
                    'tax_amount': self.price_subtotal * balance_multiplicator * (tax_id.amount/100) * currency_rate_save,
                    'base_amount_currency': self.price_subtotal * balance_multiplicator,
                    'tax_amount_currency': self.price_subtotal * balance_multiplicator * (tax_id.amount/100),
                    'tax': tax_id,
                    'exemption_reason': tax_id.name,
                    'tax_rate_transferred': tax_id.amount / 100,
                    'cfdi_name': self.get_tax_cfdi_name(tax_id)
                }
                tax_detail.append(line_val)
        values["tax_details"] = tax_detail
        return values

    def _l10n_mx_edi_get_custom_numbers(self):
        return []

    def get_tax_cfdi_name(self, tax_id):
        tags = set()
        for tag in tax_id.invoice_repartition_line_ids.tag_ids:
            tags.add(tag)
        tags = list(tags)
        if len(tags) == 1:
            return {'ISR': '001', 'IVA': '002', 'IEPS': '003'}.get(tags[0].name)
        elif tax_id.l10n_mx_tax_type == 'Exento':
            return '002'
        else:
            return None
