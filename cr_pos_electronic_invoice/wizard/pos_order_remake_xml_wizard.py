import base64
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PosOrderRemakeXMLWizard(models.TransientModel):
    _name = 'pos.order.remake_xml'
    _description = 'Asistente de Regeneración de XML para POS'

    order_id = fields.Many2one('pos.order', string='Orden POS')
    keep_clave = fields.Boolean(string='Mantener Clave', default=True, help="Solo se generará un nuevo código de seguridad de la clave")
    keep_date = fields.Boolean(string='Mantener Fecha', default=True)
    new_date = fields.Date(string='Nueva Fecha de Emisión')

    eicr_mensaje_hacienda = fields.Text(related='order_id.respuesta_tributacion', readonly=True)
    eicr_date = fields.Datetime(related='order_id.fecha', readonly=True)
    eicr_clave = fields.Char(related="order_id.number_electronic", readonly=True)
    eicr_consecutivo = fields.Char(related="order_id.name", readonly=True)

    @api.multi
    def action_remake_xml_confirm(self):
        _logger.info(self)

        # Store old values for logging
        old_clave = self.order_id.number_electronic
        old_date = self.order_id.fecha
        old_consecutivo = self.order_id.name

        _logger.info("Regenerando XML para la orden POS %s" % self.order_id.id)
        _logger.info(
            "Valores antiguos - Clave: %s, Fecha: %s, Consecutivo: %s"
            % (old_clave, old_date, old_consecutivo)
        )

        # List to collect changes for the message
        changes = []

        # Handle date change
        if not self.keep_date:
            if self.new_date:
                import datetime
                import pytz
                # Convert date to datetime with Costa Rica timezone
                new_datetime = datetime.datetime.combine(self.new_date, datetime.datetime.min.time())
                new_datetime_cr = pytz.timezone('America/Costa_Rica').localize(new_datetime)
                self.order_id.fecha = new_datetime_cr.strftime('%Y-%m-%d %H:%M:%S')
                self.order_id.date_issuance = new_datetime_cr.strftime("%Y-%m-%dT%H:%M:%S-06:00")
                changes.append("Fecha de Emisión: %s → %s" % (old_date, self.order_id.fecha))
            else:
                self.order_id.fecha = None
                self.order_id.date_issuance = None
                changes.append("Fecha de Emisión: %s → (se regenerará)" % old_date)

        # Handle clave regeneration
        if not self.keep_clave:
            sequence_id = self.env["eicr.tools"].get_sequence(self.order_id)
            if not sequence_id:
                raise UserError(
                    _(
                        "No se ha configurado una secuencia para la orden POS. Por favor, configure una secuencia en la configuración del punto de venta."
                    )
                )
            new_consecutivo = sequence_id.next_by_id()
            self.order_id.name = new_consecutivo
            _logger.info("Consecutivo %s -> %s" % (old_consecutivo, new_consecutivo))
            changes.append("Consecutivo: %s → %s" % (old_consecutivo, new_consecutivo))

        # Clear existing XML to force regeneration
        self.order_id.xml_comprobante = False
        self.order_id.state_tributacion = False

        # Regenerate XML using the same logic as when creating the order
        xml_firmado = self.env['eicr.tools'].get_xml(self.order_id)

        if xml_firmado:
            self.order_id.xml_comprobante = xml_firmado

            documento = 'FacturaElectronica' if self.env['eicr.tools']._validar_receptor(self.order_id.partner_id) else 'TiqueteElectronico'
            self.order_id.fname_xml_comprobante = documento + '_' + self.order_id.number_electronic + '.xml'
            self.order_id.state_tributacion = 'pendiente'

            # Log new values
            new_consecutivo = self.order_id.name
            new_clave = self.order_id.number_electronic
            
            if not self.keep_clave:
                changes.append("Clave: %s → %s" % (old_clave, new_clave))

            # Post message to chatter with all changes
            if changes:
                mensaje = "<p><strong>XML Regenerado</strong></p><ul>"
                for change in changes:
                    mensaje += "<li>%s</li>" % change
                mensaje += "</ul>"

                self.order_id.message_post(
                    body=mensaje, subtype="mail.mt_note", message_type="comment"
                )

            _logger.info("XML regenerado exitosamente para orden %s" % self.order_id.id)
        else:
            raise UserError(_("Error al regenerar el XML. Por favor, verifique la configuración."))

        return {'type': 'ir.actions.act_window_close'}
