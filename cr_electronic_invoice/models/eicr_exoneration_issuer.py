# -*- coding: utf-8 -*-
from odoo import models, fields
import logging

_logger = logging.getLogger(__name__)

class ElectronicInvoiceCostaRicaExonerationIssuer(models.Model):
    _name = 'eicr.exoneration_issuer'
    _description = 'Emisor de la Exoneración'

    active = fields.Boolean("Activo", default=True)
    code = fields.Char('Código')
    name = fields.Char('Descripción')
    notes = fields.Text('Notas')