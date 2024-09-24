from odoo import api, models, fields
from odoo.exceptions import ValidationError
from collections import defaultdict
import math
from odoo.tools import frozendict


class AccountMove(models.Model):
    _inherit = "account.move"

    global_lines = fields.One2many(comodel_name="account.global.line", inverse_name="move_id", string="Concepto Global", )
    is_global_concept = fields.Boolean(string="Facturacion Concepto Global",  copy=False, )
    amount_total_concept = fields.Monetary(
        string='Concepto Total',
        readonly=True, compute='_amount_total_concept', currency_field='currency_id',)

    @api.depends(
        'global_lines.price_total',
        'global_lines.currency_id')
    def _amount_total_concept(self):
        for move in self:
            total = 0.0
            for line in move.global_lines:
                total += line.price_total
            move.amount_total_concept = total

    def write(self, vals):
        res = super().write(vals)
        for record in self:
            if record.is_global_concept and record.amount_total != record.amount_total_concept:
                raise ValidationError(f"El monto global total {record.amount_total_concept} deber ser igual al monto de la factura: {record.amount_total}")
        return res

    def _prepare_edi_vals_to_export(self):
        if not self.is_global_concept:
            values = super()._prepare_edi_vals_to_export()
            return values
        self.ensure_one()

        res = {
            'record': self,
            'balance_multiplicator': -1 if self.is_inbound() else 1,
            'invoice_line_vals_list': [],
        }

        # Invoice lines details.
        for index, line in enumerate(self.global_lines, start=1):
            line_vals = line._prepare_edi_vals_to_export()
            line_vals['index'] = index
            res['invoice_line_vals_list'].append(line_vals)

        # Totals.
        res.update({
            'total_price_subtotal_before_discount': sum(x['price_subtotal_before_discount'] for x in res['invoice_line_vals_list']),
            'total_price_discount': sum(x['price_discount'] for x in res['invoice_line_vals_list']),
        })
        # Global Concept
        res.update({
            "is_global_concept": True
        })

        return res

