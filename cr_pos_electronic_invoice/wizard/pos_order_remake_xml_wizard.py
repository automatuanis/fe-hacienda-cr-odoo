import base64
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PosOrderRemakeXMLWizard(models.TransientModel):
    _name = 'pos.order.remake_xml'
    _description = 'Asistente de Regeneración de XML para POS'

    order_ids = fields.Many2many('pos.order', string='Órdenes POS')
    order_line_ids = fields.One2many(
        'pos.order.remake_xml.line', 'wizard_id', string='Órdenes a Procesar'
    )

    keep_clave = fields.Boolean(string='Mantener Clave', default=True, help="Solo se generará un nuevo código de seguridad de la clave")
    keep_date = fields.Boolean(string='Mantener Fecha', default=True)
    new_date = fields.Date(string='Nueva Fecha de Emisión')

    order_count = fields.Integer(string='Total Seleccionadas', compute='_compute_counts')
    processable_count = fields.Integer(string='Procesables', compute='_compute_counts')
    blocked_count = fields.Integer(string='Bloqueadas', compute='_compute_counts')

    # Keep backward compatibility fields for single order
    order_id = fields.Many2one('pos.order', string='Orden POS')
    eicr_mensaje_hacienda = fields.Text(related='order_id.respuesta_tributacion', readonly=True)
    eicr_date = fields.Datetime(related='order_id.fecha', readonly=True)
    eicr_clave = fields.Char(related="order_id.number_electronic", readonly=True)
    eicr_consecutivo = fields.Char(related="order_id.name", readonly=True)

    @api.depends('order_line_ids')
    def _compute_counts(self):
        for wizard in self:
            wizard.order_count = len(wizard.order_line_ids)
            wizard.processable_count = len(
                wizard.order_line_ids.filtered(lambda l: l.can_process)
            )
            wizard.blocked_count = len(
                wizard.order_line_ids.filtered(lambda l: not l.can_process)
            )

    @api.model
    def default_get(self, fields_list):
        res = super(PosOrderRemakeXMLWizard, self).default_get(fields_list)

        order_ids = self.env.context.get('active_ids', [])
        active_model = self.env.context.get('active_model', '')

        if active_model == 'pos.order' and order_ids:
            orders = self.env['pos.order'].browse(order_ids)
            res['order_ids'] = [(6, 0, order_ids)]

            lines = []
            for order in orders:
                can_process = order.state_tributacion != 'aceptado'
                lines.append((0, 0, {
                    'order_id': order.id,
                    'order_name': order.name,
                    'order_date': order.fecha,
                    'partner_name': order.partner_id.name if order.partner_id else '',
                    'amount_total': order.amount_total,
                    'state_tributacion': order.state_tributacion,
                    'respuesta_tributacion': order.respuesta_tributacion,
                    'can_process': can_process,
                }))
            res['order_line_ids'] = lines

            if len(order_ids) == 1:
                res['order_id'] = order_ids[0]

        return res

    def _process_single_order(self, order):
        """Process a single order for XML regeneration. Returns (success, changes_list)."""
        old_clave = order.number_electronic
        old_date = order.fecha
        old_consecutivo = order.name

        changes = []

        # Handle date change
        if not self.keep_date:
            if self.new_date:
                import datetime as dt
                import pytz
                new_datetime = dt.datetime.combine(self.new_date, dt.datetime.min.time())
                new_datetime_cr = pytz.timezone('America/Costa_Rica').localize(new_datetime)
                order.fecha = new_datetime_cr.strftime('%Y-%m-%d %H:%M:%S')
                order.date_issuance = new_datetime_cr.strftime("%Y-%m-%dT%H:%M:%S-06:00")
                changes.append("Fecha de Emisión: %s → %s" % (old_date, order.fecha))
            else:
                order.fecha = None
                order.date_issuance = None
                changes.append("Fecha de Emisión: %s → (se regenerará)" % old_date)

        # Handle clave regeneration
        if not self.keep_clave:
            order.number_electronic = None

        # Clear existing XML to force regeneration
        order.xml_comprobante = False
        order.state_tributacion = False

        # Regenerate XML
        xml_firmado = self.env['eicr.tools'].get_xml(order)

        if xml_firmado:
            order.xml_comprobante = xml_firmado
            documento = 'FacturaElectronica' if self.env['eicr.tools']._validar_receptor(order.partner_id) else 'TiqueteElectronico'
            order.fname_xml_comprobante = documento + '_' + order.number_electronic + '.xml'
            order.state_tributacion = 'pendiente'

            new_clave = order.number_electronic
            if not self.keep_clave:
                changes.append("Clave: %s → %s" % (old_clave, new_clave))

            return True, changes
        else:
            raise UserError(_("Error al regenerar el XML para orden %s.") % order.name)

    @api.multi
    def action_remake_xml_confirm(self):
        _logger.info(self)

        # Determine which orders to process
        orders_to_process = []

        if self.order_id and not self.order_line_ids:
            # Single order mode (backward compatibility)
            orders_to_process = [self.order_id]
        else:
            orders_to_process = [
                line.order_id for line in self.order_line_ids if line.can_process
            ]

        if not orders_to_process:
            raise UserError(_("No hay órdenes procesables seleccionadas."))

        processed_count = 0
        error_count = 0

        for order in orders_to_process:
            try:
                success, changes = self._process_single_order(order)
                if success:
                    processed_count += 1
                    if changes:
                        _logger.info("XML regenerado para orden %s: %s" % (order.name, ', '.join(changes)))
                    else:
                        _logger.info("XML regenerado para orden %s" % order.name)
                self.env.cr.commit()
            except Exception as e:
                error_count += 1
                self.env.cr.rollback()
                _logger.error("Error regenerando XML para orden %s: %s" % (order.name, str(e)))

        if len(orders_to_process) > 1:
            message = "Se procesaron %d órdenes correctamente." % processed_count
            if error_count > 0:
                message += " %d órdenes tuvieron errores." % error_count
            _logger.info(message)

        return {'type': 'ir.actions.act_window_close'}


class PosOrderRemakeXMLLine(models.TransientModel):
    _name = 'pos.order.remake_xml.line'
    _description = 'Línea de Orden POS para Regeneración'

    wizard_id = fields.Many2one(
        'pos.order.remake_xml', string='Wizard', required=True, ondelete='cascade'
    )
    order_id = fields.Many2one('pos.order', string='Orden', required=True)
    order_name = fields.Char(string='Número', readonly=True)
    order_date = fields.Datetime(string='Fecha', readonly=True)
    partner_name = fields.Char(string='Cliente', readonly=True)
    amount_total = fields.Float(string='Total', readonly=True)
    state_tributacion = fields.Selection([
        ('pendiente', 'Pendiente'),
        ('aceptado', 'Aceptado'),
        ('rechazado', 'Rechazado'),
        ('recibido', 'Recibido'),
        ('error', 'Error'),
        ('procesando', 'Procesando'),
        ('na', 'No Aplica'),
        ('ne', 'No Encontrado'),
    ], string='Estado FE', readonly=True)
    respuesta_tributacion = fields.Text(string='Mensaje Hacienda', readonly=True)
    can_process = fields.Boolean(
        string='Procesable', default=True,
        help='Las órdenes aceptadas no pueden ser reprocesadas'
    )
