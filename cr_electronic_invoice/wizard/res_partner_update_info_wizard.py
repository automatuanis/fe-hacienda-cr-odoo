# -*- coding: utf-8 -*-

import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResPartnerUpdateInfoWizard(models.TransientModel):
    _name = "res.partner.update.info.wizard"
    _description = "Wizard para actualizar información de Hacienda de múltiples partners"

    partner_ids = fields.Many2many("res.partner", string="Partners Seleccionados")
    partner_line_ids = fields.One2many(
        "res.partner.update.info.line", "wizard_id", string="Partners a Actualizar"
    )

    total_selected = fields.Integer(string="Total Seleccionados", compute="_compute_counts")
    total_with_vat = fields.Integer(string="Con Identificación", compute="_compute_counts")
    total_without_vat = fields.Integer(string="Sin Identificación", compute="_compute_counts")

    @api.depends("partner_line_ids")
    def _compute_counts(self):
        for wizard in self:
            wizard.total_selected = len(wizard.partner_line_ids)
            wizard.total_with_vat = len(wizard.partner_line_ids.filtered(lambda l: l.vat))
            wizard.total_without_vat = len(wizard.partner_line_ids.filtered(lambda l: not l.vat))

    @api.model
    def default_get(self, fields_list):
        res = super(ResPartnerUpdateInfoWizard, self).default_get(fields_list)

        # Get partners from context
        active_ids = self.env.context.get("active_ids", [])
        if not active_ids:
            raise UserError(_("No se han seleccionado partners."))

        partners = self.env["res.partner"].browse(active_ids)

        # Create lines for each partner
        lines = []
        for partner in partners:
            activity_names = (
                ", ".join(partner.eicr_activity_ids.mapped("name"))
                if partner.eicr_activity_ids
                else ""
            )
            lines.append(
                (
                    0,
                    0,
                    {
                        "partner_id": partner.id,
                        "name": partner.name,
                        "vat": partner.vat,
                        "identification_id": partner.identification_id.id
                        if partner.identification_id
                        else False,
                        "regimen_tributario": partner.eicr_regimen
                        if hasattr(partner, "eicr_regimen")
                        else "",
                        "activity_ids": [(6, 0, partner.eicr_activity_ids.ids)],
                        "activity_names": activity_names,
                    },
                )
            )

        res["partner_ids"] = [(6, 0, active_ids)]
        res["partner_line_ids"] = lines

        return res

    @api.multi
    def action_update_info(self):
        """Update tax information for all selected partners"""
        self.ensure_one()

        success_count = 0
        error_count = 0
        errors = []

        for line in self.partner_line_ids:
            partner = line.partner_id
            if not partner.vat:
                error_count += 1
                errors.append(_("Partner %s no tiene identificación") % partner.name)
                continue

            try:
                partner.action_update_info()
                success_count += 1
                _logger.info("Updated partner %s [%s]" % (partner.name, partner.vat))
            except Exception as e:
                error_count += 1
                error_msg = _("Error actualizando %s: %s") % (partner.name, str(e))
                errors.append(error_msg)
                _logger.error(error_msg)

        # Log results
        result_message = _("Actualización completada: %d exitosos, %d errores") % (
            success_count,
            error_count,
        )
        _logger.info(result_message)
        if errors:
            for error in errors:
                _logger.warning(error)

        # Return window close action (Odoo 11 compatible)
        return {"type": "ir.actions.act_window_close"}


class ResPartnerUpdateInfoLine(models.TransientModel):
    _name = "res.partner.update.info.line"
    _description = "Línea de wizard de actualización de partners"

    wizard_id = fields.Many2one(
        "res.partner.update.info.wizard", string="Wizard", required=True, ondelete="cascade"
    )
    partner_id = fields.Many2one("res.partner", string="Partner", required=True)
    name = fields.Char(string="Nombre", readonly=True)
    vat = fields.Char(string="Identificación", readonly=True)
    identification_id = fields.Many2one(
        "identification.type", string="Tipo de Identificación", readonly=True
    )
    regimen_tributario = fields.Char(string="Régimen Tributario", readonly=True)
    activity_ids = fields.Many2many(
        "economic_activity", string="Actividades Económicas", readonly=True
    )
    activity_names = fields.Char(string="Actividades", readonly=True)
