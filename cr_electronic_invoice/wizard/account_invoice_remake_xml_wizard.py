import base64
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class EICRRemakeXMLWizard(models.TransientModel):
    _name = "eicr.remake_xml"
    _description = "Asistente de Regeneración de XML "

    invoice_ids = fields.Many2many("account.invoice", string="Facturas")
    invoice_line_ids = fields.One2many(
        "eicr.remake_xml.line", "wizard_id", string="Facturas a Procesar"
    )

    keep_clave = fields.Boolean(
        string="Mantener Clave",
        default=True,
        help="Solo se generará un nuevo código de seguridad de la clave",
    )
    keep_date = fields.Boolean(string="Mantener Fecha", default=True)
    new_date = fields.Date(string="Nueva Fecha de Emisión")

    invoice_count = fields.Integer(string="Total Seleccionadas", compute="_compute_counts")
    processable_count = fields.Integer(string="Procesables", compute="_compute_counts")
    blocked_count = fields.Integer(string="Bloqueadas", compute="_compute_counts")

    # Keep backward compatibility fields for single invoice
    invoice_id = fields.Many2one("account.invoice", string="Factura")
    eicr_mensaje_hacienda = fields.Text(related="invoice_id.respuesta_tributacion", readonly=True)
    eicr_date = fields.Datetime(related="invoice_id.fecha", readonly=True)
    eicr_clave = fields.Char(related="invoice_id.number_electronic", readonly=True)

    @api.depends("invoice_line_ids")
    def _compute_counts(self):
        for wizard in self:
            wizard.invoice_count = len(wizard.invoice_line_ids)
            wizard.processable_count = len(
                wizard.invoice_line_ids.filtered(lambda l: l.can_process)
            )
            wizard.blocked_count = len(
                wizard.invoice_line_ids.filtered(lambda l: not l.can_process)
            )

    @api.model
    def default_get(self, fields_list):
        res = super(EICRRemakeXMLWizard, self).default_get(fields_list)

        # Get active invoices from context
        invoice_ids = self.env.context.get("active_ids", [])
        active_model = self.env.context.get("active_model", "")

        if active_model == "account.invoice" and invoice_ids:
            invoices = self.env["account.invoice"].browse(invoice_ids)
            res["invoice_ids"] = [(6, 0, invoice_ids)]

            # Create invoice lines for the wizard
            lines = []
            for invoice in invoices:
                can_process = invoice.state_tributacion != "aceptado"
                lines.append(
                    (
                        0,
                        0,
                        {
                            "invoice_id": invoice.id,
                            "invoice_number": invoice.number,
                            "state_tributacion": invoice.state_tributacion,
                            "respuesta_tributacion": invoice.respuesta_tributacion,
                            "can_process": can_process,
                        },
                    )
                )
            res["invoice_line_ids"] = lines

            # For backward compatibility with single invoice
            if len(invoice_ids) == 1:
                res["invoice_id"] = invoice_ids[0]

        return res

    @api.onchange("invoice_ids")
    def _onchange_invoice_ids(self):
        """Create lines for each selected invoice"""
        # Only recreate lines if invoice_ids changed in the UI
        # (not during initial load from default_get)
        if not self.invoice_line_ids or len(self.invoice_ids) != len(self.invoice_line_ids):
            lines = []
            for invoice in self.invoice_ids:
                can_process = invoice.state_tributacion != "aceptado"
                lines.append(
                    (
                        0,
                        0,
                        {
                            "invoice_id": invoice.id,
                            "invoice_number": invoice.number,
                            "state_tributacion": invoice.state_tributacion,
                            "respuesta_tributacion": invoice.respuesta_tributacion,
                            "can_process": can_process,
                        },
                    )
                )
            self.invoice_line_ids = lines

    @api.multi
    def action_remake_xml_confirm(self):
        _logger.info(self)

        # Determine which invoices to process
        invoices_to_process = []

        # Check if we're in single invoice mode (backward compatibility)
        if self.invoice_id:
            invoices_to_process = [self.invoice_id]
        else:
            # Multi-invoice mode: only process processable invoices
            invoices_to_process = [
                line.invoice_id for line in self.invoice_line_ids if line.can_process
            ]

        if not invoices_to_process:
            raise UserError(_("No hay facturas procesables seleccionadas."))

        processed_count = 0
        error_count = 0

        for invoice in invoices_to_process:
            try:
                # Store old values for logging
                old_clave = invoice.number_electronic
                old_date = invoice.fecha
                old_consecutivo = invoice.number

                _logger.info("Regenerando XML para la factura %s" % invoice.id)
                _logger.info(
                    "Valores antiguos - Clave: %s, Fecha: %s, Consecutivo: %s"
                    % (old_clave, old_date, old_consecutivo)
                )

                # List to collect changes for the message
                changes = []

                # Handle date change
                if not self.keep_date:
                    if self.new_date:
                        invoice.fecha = self.new_date
                        changes.append("Fecha de Emisión: %s → %s" % (old_date, self.new_date))
                    else:
                        invoice.fecha = None
                        changes.append("Fecha de Emisión: %s → (se regenerará)" % old_date)

                # Handle clave regeneration
                if not self.keep_clave:
                    sequence_id = self.env["eicr.tools"].get_sequence(invoice)
                    if not sequence_id:
                        raise UserError(
                            _(
                                "No se ha configurado una secuencia para la factura electrónica. Por favor, configure una secuencia en la configuración de la empresa."
                            )
                        )
                    new_consecutivo = sequence_id.next_by_id()
                    invoice.number = new_consecutivo
                    _logger.info("Consecutivo %s -> %s" % (old_consecutivo, new_consecutivo))

                invoice.xml_comprobante = False
                if invoice.type in ("out_invoice", "out_refund"):
                    invoice._action_out_invoice_open(invoice)
                elif invoice.type in ("in_invoice", "in_refund"):
                    invoice._action_in_invoice_open(invoice)

                new_consecutivo = invoice.number
                new_clave = invoice.number_electronic

                if not self.keep_clave:
                    changes.append("Consecutivo: %s → %s" % (old_consecutivo, new_consecutivo))
                    changes.append("Clave: %s → %s" % (old_clave, new_clave))

                # Post message to chatter with all changes
                if changes:
                    mensaje = "<p><strong>XML Regenerado</strong></p><ul>"
                    for change in changes:
                        mensaje += "<li>%s</li>" % change
                    mensaje += "</ul>"

                    invoice.message_post(
                        body=mensaje, subtype="mail.mt_note", message_type="comment"
                    )

                processed_count += 1

            except Exception as e:
                _logger.error("Error al regenerar XML para factura %s: %s" % (invoice.id, str(e)))
                error_count += 1
                invoice.message_post(
                    body="<p><strong>Error al Regenerar XML</strong></p><p>%s</p>" % str(e),
                    subtype="mail.mt_note",
                    message_type="comment",
                )

        # Show summary message
        if len(invoices_to_process) > 1:
            message = "Se procesaron %d facturas correctamente." % processed_count
            if error_count > 0:
                message += " %d facturas tuvieron errores." % error_count

            # Post summary to wizard or just return
            # In Odoo 11, we can use a UserError to show a message or just return
            # Let's return a simple action that closes the wizard
            return {"type": "ir.actions.act_window_close"}
        else:
            # For single invoice, return to the invoice
            return {"type": "ir.actions.act_window_close"}


class EICRRemakeXMLLine(models.TransientModel):
    _name = "eicr.remake_xml.line"
    _description = "Línea de Factura para Regeneración"

    wizard_id = fields.Many2one(
        "eicr.remake_xml", string="Wizard", required=True, ondelete="cascade"
    )
    invoice_id = fields.Many2one("account.invoice", string="Factura", required=True)
    invoice_number = fields.Char(string="Número", readonly=True)
    state_tributacion = fields.Selection(
        [
            ("pendiente", "Pendiente"),
            ("aceptado", "Aceptado"),
            ("rechazado", "Rechazado"),
            ("recibido", "Recibido"),
            ("error", "Error"),
            ("procesando", "Procesando"),
            ("na", "No Aplica"),
            ("ne", "No Encontrado"),
        ],
        string="Estado FE",
        readonly=True,
    )
    respuesta_tributacion = fields.Text(string="Mensaje Hacienda", readonly=True)
    can_process = fields.Boolean(
        string="Procesable", default=True, help="Las facturas aceptadas no pueden ser reprocesadas"
    )
