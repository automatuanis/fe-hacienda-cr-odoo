# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class EconomicActivity(models.Model):
    _name = "economic_activity"

    active = fields.Boolean(string="Activo", required=False, default=True)
    code = fields.Char(string="Código", required=False, )
    name = fields.Char(string="Nombre", required=False, )
    tipo = fields.Selection(
        string="Tipo",
        required=False,
        selection=[
            ("rut", "Registro Único Tributario de Hacienda"),
            ("ciiu3", "CIIU revision 3"),
            ("ciiu4", "CIIU revision 4"),
        ],
        default="rut",
    )
    description = fields.Char(string="Descripción", required=False, )
    partner_ids = fields.Many2many(
        "res.partner",
        "economic_activity_res_partner_rel",
        "economic_activity_id",
        "res_partner_id",
        string="Contactos Asociados",
    )

    @api.multi
    def name_get(self):
        """Override name_get to show 'code - name' format in UI"""
        result = []
        for record in self:
            if record.code and record.name:
                name = "%s - %s" % (record.code, record.name)
            elif record.code:
                name = record.code
            elif record.name:
                name = record.name
            else:
                name = _("Economic Activity")
            result.append((record.id, name))
        return result
