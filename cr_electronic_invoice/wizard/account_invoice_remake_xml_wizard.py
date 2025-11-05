import base64
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class EICRRemakeXMLWizard(models.TransientModel):
    _name = 'eicr.remake_xml'
    _description = 'Asistente de Regeneración de XML '

    invoice_id = fields.Many2one('account.invoice', string='Factura')
    keep_clave = fields.Boolean(string='Mantener Clave', default=True, help="Solo se generará un nuevo código de seguridad de la clave")
    keep_date = fields.Boolean(string='Mantener Fecha', default=True)
    new_date = fields.Date(string='Nueva Fecha de Emisión')

    eicr_mensaje_hacienda = fields.Text(related='invoice_id.respuesta_tributacion_preview', readonly=True)
    eicr_date = fields.Datetime(related='invoice_id.fecha', readonly=True)
    eicr_clave = fields.Char(related="invoice_id.number_electronic", readonly=True)

    @api.multi
    def action_remake_xml_confirm(self):
        _logger.info(self)

        # Store old values for logging
        old_clave = self.invoice_id.number_electronic
        old_date = self.invoice_id.fecha
        old_consecutivo = self.invoice_id.number

        _logger.info("Regenerando XML para la factura %s" % self.invoice_id.id)
        _logger.info(
            "Valores antiguos - Clave: %s, Fecha: %s, Consecutivo: %s"
            % (old_clave, old_date, old_consecutivo)
        )

        # List to collect changes for the message
        changes = []

        # Handle date change
        if not self.keep_date:
            if self.new_date:
                self.invoice_id.fecha = self.new_date
                changes.append("Fecha de Emisión: %s → %s" % (old_date, self.new_date))
            else:
                self.invoice_id.fecha = None
                changes.append("Fecha de Emisión: %s → (se regenerará)" % old_date)

        # Handle clave regeneration
        if not self.keep_clave:
            sequence_id = self.env["eicr.tools"].get_sequence(self.invoice_id)
            if not sequence_id:
                raise UserError(
                    _(
                        "No se ha configurado una secuencia para la factura electrónica. Por favor, configure una secuencia en la configuración de la empresa."
                    )
                )
            new_consecutivo = sequence_id.next_by_id()
            self.number = new_consecutivo
            _logger.info("Consecutivo %s -> %s" % (old_consecutivo, new_consecutivo))

        self.invoice_id.xml_comprobante = False
        if self.invoice_id.type in ("out_invoice", "out_refund"):
            self.invoice_id._action_out_invoice_open(self.invoice_id)
        elif self.invoice_id.type in ("in_invoice", "in_refund"):
            self.invoice_id._action_in_invoice_open(self.invoice_id)

        new_consecutivo = self.invoice_id.number
        new_clave = self.invoice_id.number_electronic
        
        if not self.keep_clave:
            changes.append("Consecutivo: %s → %s" % (old_consecutivo, new_consecutivo))
            changes.append("Clave: %s → %s" % (old_clave, new_clave))

            # Post message to chatter with all changes
        if changes:
            mensaje = "<p><strong>XML Regenerado</strong></p><ul>"
            for change in changes:
                mensaje += "<li>%s</li>" % change
            mensaje += "</ul>"

            self.invoice_id.message_post(
                body=mensaje, subtype="mail.mt_note", message_type="comment"
            )

        return self.invoice_id
