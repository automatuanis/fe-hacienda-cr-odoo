# -*- coding: utf-8 -*-
from odoo import models, fields
import logging

_logger = logging.getLogger(__name__)


class DiscountType(models.Model):
    _name = "discount.type"
    _description = "Tipo de Descuento"

    active = fields.Boolean("Activo", default=True)
    sequence = fields.Char("Secuencia")
    name = fields.Char("Nombre")
    notes = fields.Text("Notas")
