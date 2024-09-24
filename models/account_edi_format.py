from odoo import api, models, fields, tools, _
from odoo.tools.xml_utils import _check_with_xsd
from odoo.tools.float_utils import float_round, float_is_zero

import logging
import re
import base64
import json
import requests
import random
import string

from lxml import etree
from lxml.objectify import fromstring
from math import copysign
from datetime import datetime
from io import BytesIO
from json.decoder import JSONDecodeError

from odoo.tools.zeep import Client

_logger = logging.getLogger(__name__)
EQUIVALENCIADR_PRECISION_DIGITS = 10
CFDI_DATE_FORMAT = '%Y-%m-%dT%H:%M:%S'


class AccountEdiFormat(models.Model):
    _inherit = "account.edi.format"

    def _l10n_mx_edi_get_invoice_templates_global(self):
        return self.env.ref('global_concepts.cfdiv40Global'), self.sudo().env.ref('l10n_mx_edi.xsd_cached_cfdv40_xsd', False)

    def _l10n_mx_edi_get_invoice_cfdi_values(self, invoice):
        res = super()._l10n_mx_edi_get_invoice_cfdi_values(invoice)
        if invoice.is_global_concept:
            tax_values = {
                'tax_details_transferred_global': self.get_tax_detail_transferred_global(res),
                'tax_details_withholding_global': self.get_tax_details_withholding_global(res)
            }
            res.update(tax_values)
        return res

    def get_tax_detail_transferred_global(self, data):
        base_amount_currency = 0.0
        tax_amount_currency = 0.0
        base_amount = 0.0
        tax_amount = 0.0
        tax_details = []
        for line in data.get('invoice_line_vals_list', []):
            tax_detail_transferred_global = line.get('tax_details_transferred_global', {})
            for tax_line in tax_detail_transferred_global.get("tax_details", []):
                base_amount_currency += tax_line.get('base_amount_currency', 0.0)
                tax_amount_currency += tax_line.get('tax_amount_currency', 0.0)
                base_amount += tax_line.get('base_amount', 0.0)
                tax_amount += tax_line.get('tax_amount', 0.0)
                tax_details.append(tax_line)
        values = {
            'base_amount_currency': base_amount_currency,
            'tax_amount_currency': tax_amount_currency,
            'base_amount': base_amount,
            'tax_amount': tax_amount,
            'tax_details': tax_details
        }
        return values

    def get_tax_details_withholding_global(self, data):
        base_amount_currency = 0.0
        tax_amount_currency = 0.0
        base_amount = 0.0
        tax_amount = 0.0
        tax_details = []
        for line in data.get('invoice_line_vals_list', []):
            tax_details_withholding = line.get('tax_details_withholding', {})
            for tax_line in tax_details_withholding.get('tax_details', []):
                base_amount_currency += tax_line.get('base_amount_currency', 0.0)
                tax_amount_currency += tax_line.get('tax_amount_currency', 0.0)
                base_amount += tax_line.get('base_amount', 0.0)
                tax_amount += tax_line.get('tax_amount', 0.0)
                tax_details.append(tax_line.get('tax_details'))
        values = {
            'base_amount_currency': base_amount_currency,
            'tax_amount_currency': tax_amount_currency,
            'base_amount': base_amount,
            'tax_amount': tax_amount,
            'tax_details': tax_details
        }
        return values

    def _l10n_mx_edi_export_invoice_cfdi(self, invoice):
        if not invoice.is_global_concept:
            res = super()._l10n_mx_edi_export_invoice_cfdi(invoice)
            return res
        # override
        # == CFDI values ==
        cfdi_values = self._l10n_mx_edi_get_invoice_cfdi_values(invoice)
        qweb_template, xsd_attachment = self._l10n_mx_edi_get_invoice_templates_global()

        # == Generate the CFDI ==
        cfdi = qweb_template._render(cfdi_values)
        decoded_cfdi_values = invoice._l10n_mx_edi_decode_cfdi(cfdi_data=cfdi)
        cfdi_cadena_crypted = cfdi_values['certificate'].sudo().get_encrypted_cadena(decoded_cfdi_values['cadena'])
        decoded_cfdi_values['cfdi_node'].attrib['Sello'] = cfdi_cadena_crypted

        # == Optional check using the XSD ==
        xsd_datas = base64.b64decode(xsd_attachment.datas) if xsd_attachment else None

        res = {
            'cfdi_str': etree.tostring(decoded_cfdi_values['cfdi_node'], pretty_print=True, xml_declaration=True, encoding='UTF-8'),
        }

        if xsd_datas:
            try:
                with BytesIO(xsd_datas) as xsd:
                    _check_with_xsd(decoded_cfdi_values['cfdi_node'], xsd)
            except (IOError, ValueError):
                _logger.info(_('The xsd file to validate the XML structure was not found'))
            except Exception as e:
                res['errors'] = str(e).split('\\n')

        return res
