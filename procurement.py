# SPDX-FileCopyrightText: 2026 Custom GNU Health
# SPDX-License-Identifier: GPL-3.0-or-later

from datetime import datetime

from trytond.exceptions import UserError
from trytond.model import ModelSQL, ModelView, Unique, fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval
from trytond.report import Report
from trytond.transaction import Transaction
from trytond.wizard import Button, StateTransition, StateView, Wizard

__all__ = [
    'MedicalPurchaseAudit',
    'MedicalPurchaseProcurementRound',
    'MedicalPurchaseProcurementProposal',
    'MedicalPurchaseProcurementProposalBudgetRequestReport',
    'UploadProcurementResponseStart',
    'StartProcurementRoundStart',
    'StartProcurementRoundParty',
    'UploadProcurementResponseWizard',
    'StartProcurementRoundWizard',
    'SelectProcurementWinnerStart',
    'SelectProcurementWinnerWizard',
    'GenerateProcurementPurchaseStart',
    'GenerateProcurementPurchaseWizard',
]

ACTIVE_ROUND_STATES = [
    'draft', 'in_comparison', 'winner_selected', 'purchase_created']


class MedicalPurchaseAudit(metaclass=PoolMeta):
    __name__ = 'gnuhealth.medical.purchase.audit'

    procurement_rounds = fields.One2Many(
        'gnuhealth.medical.purchase.procurement.round', 'audit_document',
        'Rondas de Procurement', readonly=True)
    procurement_round_count = fields.Function(
        fields.Integer('Cantidad de Rondas'),
        'get_procurement_metrics')
    has_active_procurement_round = fields.Function(
        fields.Boolean('Tiene Ronda Activa'),
        'get_procurement_metrics')

    @classmethod
    def get_procurement_metrics(cls, records, name):
        result = {}
        for record in records:
            if name == 'procurement_round_count':
                result[record.id] = len(record.procurement_rounds)
            elif name == 'has_active_procurement_round':
                result[record.id] = any(
                    round_.state in ACTIVE_ROUND_STATES
                    for round_ in record.procurement_rounds)
            else:
                result[record.id] = None
        return result


class MedicalPurchaseProcurementRound(ModelSQL, ModelView):
    'Medical Purchase Procurement Round'
    __name__ = 'gnuhealth.medical.purchase.procurement.round'

    name = fields.Char('Nombre', required=True, readonly=True)
    audit_document = fields.Many2One(
        'gnuhealth.medical.purchase.audit', 'Documento Origen',
        required=True, readonly=True, ondelete='RESTRICT')
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('in_comparison', 'En Comparacion'),
        ('winner_selected', 'Ganador Seleccionado'),
        ('purchase_created', 'Compra Generada'),
        ('done', 'Finalizada'),
        ('cancelled', 'Cancelada'),
    ], 'Estado', readonly=True, sort=False)
    date = fields.DateTime('Fecha', readonly=True)
    date_display = fields.Function(
        fields.Char('Fecha'), 'get_date_display')
    created_by = fields.Many2One('res.user', 'Creado por', readonly=True)
    observations = fields.Text(
        'Observaciones',
        states={'readonly': Eval('state').in_(['done', 'cancelled'])},
        depends=['state'])
    proposals = fields.One2Many(
        'gnuhealth.medical.purchase.procurement.proposal', 'round',
        'Propuestas',
        states={'readonly': Eval('state') != 'in_comparison'},
        depends=['state'])
    winner_proposal = fields.Many2One(
        'gnuhealth.medical.purchase.procurement.proposal',
        'Propuesta Ganadora', readonly=True,
        domain=[('round', '=', Eval('id', -1))], depends=['id'])
    generated_purchase = fields.Many2One(
        'purchase.purchase', 'Compra Generada', readonly=True)
    is_closed = fields.Function(
        fields.Boolean('Cerrada'), 'get_is_closed')
    proposal_count = fields.Function(
        fields.Integer('Cantidad de Propuestas'),
        'get_round_metrics')
    request_generated_count = fields.Function(
        fields.Integer('Solicitudes Generadas'),
        'get_round_metrics')
    response_received_count = fields.Function(
        fields.Integer('Respuestas Recibidas'),
        'get_round_metrics')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._buttons.update({
            'cancel_round': {
                'invisible': Eval('state').in_(['done', 'cancelled']),
                'depends': ['state'],
            },
        })

    @staticmethod
    def default_state():
        return 'draft'

    @classmethod
    def default_date(cls):
        return datetime.utcnow()

    @classmethod
    def _current_user_has_group(cls, group_xml_id):
        pool = Pool()
        User = pool.get('res.user')
        ModelData = pool.get('ir.model.data')
        try:
            group_id = ModelData.get_id(
                'z_001_medical_purchase_procurement', group_xml_id)
        except KeyError:
            return False
        current_user = User(Transaction().user)
        return any(group.id == group_id for group in current_user.groups)

    @classmethod
    def _ensure_procurement_manager(cls):
        if not cls._current_user_has_group('z_gestor_procura_medica'):
            raise UserError(
                'No tiene los permisos necesarios para gestionar '
                'rondas de procurement medico.')

    @classmethod
    def get_is_closed(cls, records, name):
        return {
            record.id: record.state in ('done', 'cancelled')
            for record in records
        }

    @classmethod
    def get_round_metrics(cls, records, name):
        result = {}
        for record in records:
            if name == 'proposal_count':
                result[record.id] = len(record.proposals)
            elif name == 'request_generated_count':
                result[record.id] = sum(
                    1 for proposal in record.proposals
                    if proposal.request_generated)
            elif name == 'response_received_count':
                result[record.id] = sum(
                    1 for proposal in record.proposals
                    if proposal.has_response_file)
            else:
                result[record.id] = None
        return result

    @classmethod
    def get_date_display(cls, records, name):
        return {
            record.id: (
                record.date.strftime('%Y-%m-%d %H:%M:%S')
                if record.date else '')
            for record in records
        }

    @classmethod
    def create(cls, vlist):
        Audit = Pool().get('gnuhealth.medical.purchase.audit')
        vlist = [dict(v) for v in vlist]
        for values in vlist:
            audit_id = values.get('audit_document')
            if not audit_id:
                raise UserError(
                    'La ronda debe estar vinculada a un documento aceptado.')
            audit = Audit(audit_id)
            cls._validate_audit_document(audit)
            cls._validate_no_active_round(audit)
            if not values.get('name'):
                values['name'] = cls._build_round_name(audit)
            values.setdefault('date', datetime.utcnow())
            values.setdefault('created_by', Transaction().user)
            values.setdefault('state', 'in_comparison')
        return super().create(vlist)

    @classmethod
    def write(cls, *args):
        actions = iter(args)
        allowed_fields = {
            'state', 'winner_proposal', 'generated_purchase',
            'observations',
        }
        for records, values in zip(actions, actions):
            changed = set(values.keys())
            system_change = Transaction().context.get(
                'from_procurement_round_workflow')
            for record in records:
                if (record.state in ('done', 'cancelled')
                        and changed - {'observations'}):
                    raise UserError('La ronda ya no se puede modificar.')
                if (changed - {'observations'}) and not system_change:
                    raise UserError(
                        'La ronda solo puede cambiar mediante las acciones '
                        'autorizadas.')
                if changed - allowed_fields and not system_change:
                    raise UserError(
                        'La ronda contiene cambios no permitidos por el flujo.')
        super().write(*args)

    @classmethod
    def delete(cls, records):
        for record in records:
            if record.state != 'cancelled':
                raise UserError(
                    'Solo se pueden eliminar rondas canceladas.')
        super().delete(records)

    @classmethod
    def _build_round_name(cls, audit):
        return 'Procurement %s - %s' % (
            audit.rec_name, datetime.utcnow().strftime('%Y%m%d%H%M%S'))

    @classmethod
    def _validate_audit_document(cls, audit):
        if audit.state != 'accepted':
            raise UserError(
                'Solo se puede iniciar procurement desde documentos '
                'aceptados.')
        if not audit.lines:
            raise UserError(
                'El documento aceptado no tiene medicamentos para cotizar.')

    @classmethod
    def _validate_no_active_round(cls, audit):
        active = cls.search([
            ('audit_document', '=', audit.id),
            ('state', 'in', ACTIVE_ROUND_STATES),
        ], limit=1)
        if active:
            raise UserError(
                'El documento ya tiene una ronda de procurement activa.')

    def validate_winner_can_be_selected(self, proposal):
        if self.state != 'in_comparison':
            raise UserError(
                'Solo se puede seleccionar ganador en una ronda en '
                'comparacion.')
        if proposal.round.id != self.id:
            raise UserError(
                'La propuesta seleccionada no pertenece a esta ronda.')
        proposal.validate_as_winner()

    @classmethod
    def select_winner(cls, round_, proposal):
        cls._ensure_procurement_manager()
        round_.validate_winner_can_be_selected(proposal)
        Proposal = Pool().get(
            'gnuhealth.medical.purchase.procurement.proposal')
        with Transaction().set_context(from_procurement_round_workflow=True):
            Proposal.write(round_.proposals, {
                'is_winner': False,
                'state': 'discarded',
            })
            Proposal.write([proposal], {
                'is_winner': True,
                'state': 'winner',
            })
            cls.write([round_], {
                'winner_proposal': proposal.id,
                'state': 'winner_selected',
            })

    def _validate_can_generate_purchase(self):
        if self.state != 'winner_selected':
            raise UserError(
                'La compra solo se puede generar desde una ronda con '
                'ganador seleccionado.')
        if self.generated_purchase:
            raise UserError(
                'La ronda ya tiene una compra generada.')
        if not self.winner_proposal:
            raise UserError(
                'Debe existir una propuesta ganadora antes de generar la '
                'compra.')

    def _build_purchase_description(self):
        return 'Origen: %s | Ronda: %s' % (
            self.audit_document.rec_name, self.rec_name)

    def _get_company(self):
        Company = Pool().get('company.company')
        company_id = Transaction().context.get('company')
        if not company_id:
            raise UserError(
                'Debe existir una compania activa para generar la compra.')
        return Company(company_id)

    def _get_purchase_warehouse(self, wizard_warehouse=None):
        Location = Pool().get('stock.location')
        warehouse = wizard_warehouse
        if not warehouse:
            warehouse_id = Location.get_default_warehouse()
            warehouse = Location(warehouse_id) if warehouse_id else None
        if not warehouse:
            raise UserError(
                'No se pudo resolver un deposito para la compra. '
                'Seleccione uno en el wizard.')
        return warehouse

    def _iter_purchase_source_lines(self):
        for audit_line in self.audit_document.lines:
            if not audit_line.medicament:
                raise UserError(
                    'El documento aceptado contiene una linea sin '
                    'medicamento.')
            product = audit_line.medicament.name
            if not product:
                raise UserError(
                    'El medicamento "%s" no tiene un producto asociado.'
                    % audit_line.medicament.rec_name)
            if not product.purchasable:
                raise UserError(
                    'El producto "%s" no esta habilitado para compras.'
                    % product.rec_name)
            if audit_line.unit_price is None:
                raise UserError(
                    'El documento aceptado debe tener precio unitario para '
                    'todos los medicamentos.')
            quantity = audit_line.purchase_quantity or 0
            if quantity < 0:
                raise UserError(
                    'La cantidad a comprar del documento aceptado no puede '
                    'ser menor que cero.')
            if quantity == 0:
                continue
            yield audit_line, product

    def generate_purchase(self, warehouse=None):
        pool = Pool()
        Purchase = pool.get('purchase.purchase')
        PurchaseLine = pool.get('purchase.line')
        self.__class__._ensure_procurement_manager()
        self._validate_can_generate_purchase()

        proposal = self.winner_proposal
        proposal.validate_as_winner()
        company = self._get_company()
        purchase_warehouse = self._get_purchase_warehouse(warehouse)
        party = proposal.party
        if not party:
            raise UserError(
                'La propuesta ganadora no tiene proveedor.')
        invoice_address = party.address_get(type='invoice')
        if not invoice_address:
            raise UserError(
                'El proveedor ganador no tiene direccion de facturacion.')

        purchase = Purchase(
            company=company,
            party=party,
            invoice_party=party,
            invoice_address=invoice_address,
            warehouse=purchase_warehouse,
            currency=company.currency,
            description=self._build_purchase_description(),
            reference=self.audit_document.rec_name,
            payment_term=party.supplier_payment_term,
            invoice_method=Purchase.default_invoice_method(
                company=company.id),
        )
        purchase.save()

        lines = []
        for audit_line, product in self._iter_purchase_source_lines():
            line = PurchaseLine()
            line.purchase = purchase
            line.type = 'line'
            line.product = product
            line.quantity = float(audit_line.purchase_quantity)
            line.on_change_product()
            line.unit_price = audit_line.unit_price
            line.description = '%s - Documento %s' % (
                audit_line.medicament.rec_name,
                self.audit_document.rec_name)
            if not line.unit:
                raise UserError(
                    'El producto "%s" no tiene unidad de compra valida.'
                    % product.rec_name)
            lines.append(line)

        if not lines:
            raise UserError(
                'El documento aceptado no tiene cantidades a comprar '
                'mayores a cero.')
        PurchaseLine.save(lines)

        try:
            Purchase.quote([purchase])
            Purchase.confirm([purchase])
        except Exception as exc:
            raise UserError(
                'No se pudo confirmar la compra generada: %s' % exc)

        with Transaction().set_context(from_procurement_round_workflow=True):
            self.__class__.write([self], {
                'generated_purchase': purchase.id,
                'state': 'done',
            })
            proposal.__class__.write([proposal], {
                'purchase': purchase.id,
            })
        return purchase

    @classmethod
    @ModelView.button
    def cancel_round(cls, rounds):
        cls._ensure_procurement_manager()
        for round_ in rounds:
            if round_.generated_purchase:
                raise UserError(
                    'No se puede cancelar una ronda que ya genero una compra.')
        with Transaction().set_context(from_procurement_round_workflow=True):
            cls.write(rounds, {'state': 'cancelled'})


class MedicalPurchaseProcurementProposal(ModelSQL, ModelView):
    'Medical Purchase Procurement Proposal'
    __name__ = 'gnuhealth.medical.purchase.procurement.proposal'

    round = fields.Many2One(
        'gnuhealth.medical.purchase.procurement.round', 'Ronda',
        required=True, readonly=True, ondelete='CASCADE')
    party = fields.Many2One(
        'party.party', 'Proveedor', required=True, readonly=True,
        ondelete='RESTRICT')
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('winner', 'Ganadora'),
        ('discarded', 'No Ganadora'),
    ], 'Estado', readonly=True, sort=False)
    request_generated = fields.Boolean(
        'Solicitud Generada', readonly=True)
    request_generated_date = fields.DateTime(
        'Fecha Solicitud', readonly=True)
    request_generated_date_display = fields.Function(
        fields.Char('Fecha Solicitud'),
        'get_datetime_display')
    request_generated_by = fields.Many2One(
        'res.user', 'Solicitud Generada Por', readonly=True)
    response_file = fields.Binary(
        'Archivo de Respuesta',
        filename='response_filename',
        states={'readonly': Eval('round_state') != 'in_comparison'},
        depends=['round_state'])
    response_filename = fields.Char(
        'Nombre de Archivo',
        states={'readonly': Eval('round_state') != 'in_comparison'},
        depends=['round_state'])
    response_received_date = fields.DateTime(
        'Fecha Respuesta', readonly=True)
    response_received_date_display = fields.Function(
        fields.Char('Fecha Respuesta'),
        'get_datetime_display')
    response_received_by = fields.Many2One(
        'res.user', 'Respuesta Cargada Por', readonly=True)
    has_response_file = fields.Function(
        fields.Boolean('Tiene Respuesta'),
        'get_has_response_file')
    observations = fields.Text(
        'Observaciones',
        states={'readonly': Eval('round_state') != 'in_comparison'},
        depends=['round_state'])
    is_winner = fields.Boolean('Ganadora', readonly=True)
    purchase = fields.Many2One(
        'purchase.purchase', 'Compra Vinculada', readonly=True)
    round_state = fields.Function(
        fields.Selection([
            ('draft', 'Borrador'),
            ('in_comparison', 'En Comparacion'),
            ('winner_selected', 'Ganador Seleccionado'),
            ('purchase_created', 'Compra Generada'),
            ('done', 'Finalizada'),
            ('cancelled', 'Cancelada'),
        ], 'Estado Ronda'), 'get_round_state')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        table = cls.__table__()
        cls._sql_constraints = [
            ('round_party_unique',
             Unique(table, table.round, table.party),
             'Cada proveedor solo puede tener una propuesta por ronda.'),
        ]
        cls._buttons.update({
            'generate_budget_request': {
                'invisible': Eval('round_state') != 'in_comparison',
                'depends': ['round_state'],
            },
            'load_response': {
                'invisible': Eval('round_state') != 'in_comparison',
                'depends': ['round_state'],
            },
            'mark_as_winner': {
                'invisible': Eval('round_state') != 'in_comparison',
                'depends': ['round_state'],
            },
        })

    @staticmethod
    def default_state():
        return 'draft'

    @classmethod
    def get_round_state(cls, records, name):
        return {
            record.id: record.round.state if record.round else None
            for record in records
        }

    @classmethod
    def get_has_response_file(cls, records, name):
        return {
            record.id: bool(record.response_file)
            for record in records
        }

    @classmethod
    def get_datetime_display(cls, records, name):
        field_name = name.replace('_display', '')
        return {
            record.id: (
                getattr(record, field_name).strftime('%Y-%m-%d %H:%M:%S')
                if getattr(record, field_name) else '')
            for record in records
        }

    @classmethod
    def create(cls, vlist):
        if not Transaction().context.get('from_procurement_start_wizard'):
            raise UserError(
                'Las propuestas solo se pueden crear desde el wizard de '
                'inicio de ronda.')
        return super().create(vlist)

    @classmethod
    def write(cls, *args):
        actions = iter(args)
        system_change = Transaction().context.get(
            'from_procurement_round_workflow')
        request_report_change = Transaction().context.get(
            'from_procurement_request_report')
        for records, values in zip(actions, actions):
            values = dict(values)
            changed = set(values.keys())
            editable_fields = {
                'observations', 'response_file', 'response_filename',
            }
            response_tracking_fields = {
                'response_received_date', 'response_received_by',
            }
            workflow_fields = {
                'is_winner', 'state', 'purchase',
            }
            request_fields = {
                'request_generated', 'request_generated_date',
                'request_generated_by',
            }
            if 'response_file' in values:
                if values.get('response_file'):
                    values['response_received_date'] = datetime.utcnow()
                    values['response_received_by'] = Transaction().user
                else:
                    values['response_filename'] = None
                    values['response_received_date'] = None
                    values['response_received_by'] = None
                changed = set(values.keys())

            for record in records:
                if record.round.state != 'in_comparison':
                    if changed - workflow_fields - request_fields:
                        raise UserError(
                            'La propuesta ya no se puede editar fuera de la '
                            'etapa de comparacion.')
                if changed & workflow_fields and not system_change:
                    raise UserError(
                        'La propuesta solo puede cambiar de estado desde las '
                        'acciones autorizadas.')
                if changed & request_fields and not request_report_change:
                    raise UserError(
                        'La solicitud de presupuesto solo se puede marcar '
                        'desde el reporte autorizado.')
                if changed - editable_fields - response_tracking_fields - workflow_fields - request_fields:
                    raise UserError(
                        'La propuesta contiene cambios no permitidos por el '
                        'flujo.')
            super().write(records, values)

    def validate_as_winner(self):
        if not self.response_file:
            raise UserError(
                'Debe cargar la respuesta del proveedor antes de seleccionar '
                'un ganador.')

    @classmethod
    def mark_request_generated(cls, proposals):
        with Transaction().set_context(from_procurement_request_report=True):
            cls.write(proposals, {
                'request_generated': True,
                'request_generated_date': datetime.utcnow(),
                'request_generated_by': Transaction().user,
            })

    def get_rec_name(self, name):
        if self.party:
            return self.party.rec_name
        return super().get_rec_name(name)

    @classmethod
    @ModelView.button_action(
        'z_001_medical_purchase_procurement.report_procurement_budget_request')
    def generate_budget_request(cls, proposals):
        cls._ensure_manager_for_buttons()
        cls.mark_request_generated(proposals)

    @classmethod
    @ModelView.button_action(
        'z_001_medical_purchase_procurement.act_upload_procurement_response_wizard')
    def load_response(cls, proposals):
        cls._ensure_manager_for_buttons()

    @classmethod
    @ModelView.button
    def mark_as_winner(cls, proposals):
        cls._ensure_manager_for_buttons()
        for proposal in proposals:
            if not proposal.round:
                raise UserError(
                    'La propuesta no esta vinculada a una ronda.')
            proposal.round.__class__.select_winner(proposal.round, proposal)

    @classmethod
    def _ensure_manager_for_buttons(cls):
        Pool().get(
            'gnuhealth.medical.purchase.procurement.round'
        )._ensure_procurement_manager()


class MedicalPurchaseProcurementProposalBudgetRequestReport(Report):
    __name__ = 'z_001_medical_purchase_procurement.procurement_budget_request'

    @classmethod
    def execute(cls, ids, data):
        Proposal = Pool().get('gnuhealth.medical.purchase.procurement.proposal')
        proposals = Proposal.browse(ids)
        if not proposals:
            raise UserError(
                'No se encontraron propuestas para generar la solicitud de '
                'presupuesto.')
        content = cls._build_report_content(proposals)
        filename = 'solicitud_presupuesto'
        if len(proposals) == 1 and proposals[0].party:
            filename = 'solicitud_presupuesto_%s' % proposals[0].party.id
        return 'txt', content.encode('utf-8'), False, filename

    @classmethod
    def _build_report_content(cls, proposals):
        blocks = []
        for proposal in proposals:
            round_ = proposal.round
            audit = round_.audit_document
            lines = [
                'Solicitud de Presupuesto',
                '========================',
                'Proveedor: %s' % proposal.party.rec_name,
                'Ronda: %s' % round_.rec_name,
                'Documento origen: %s' % audit.rec_name,
                'Fecha: %s' % datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                '',
                'Detalle solicitado:',
            ]
            for audit_line in audit.lines:
                if not audit_line.medicament:
                    continue
                lines.append(
                    '- %s | Cantidad: %s'
                    % (audit_line.medicament.rec_name,
                       audit_line.purchase_quantity or 0))
            blocks.append('\n'.join(lines))
        return '\n\n'.join(blocks)


class UploadProcurementResponseStart(ModelView):
    'Upload Procurement Response Start'
    __name__ = 'gnuhealth.medical.purchase.procurement.upload_response'

    proposal = fields.Many2One(
        'gnuhealth.medical.purchase.procurement.proposal', 'Propuesta',
        readonly=True)
    party = fields.Many2One('party.party', 'Proveedor', readonly=True)
    response_filename = fields.Char('Nombre de Archivo', required=True)
    response_file = fields.Binary(
        'Archivo de Respuesta', filename='response_filename', required=True)

    @classmethod
    def default_proposal(cls):
        active_id = Transaction().context.get('active_id')
        if active_id:
            return active_id

    @classmethod
    def default_party(cls):
        Proposal = Pool().get('gnuhealth.medical.purchase.procurement.proposal')
        active_id = Transaction().context.get('active_id')
        if not active_id:
            return
        proposal = Proposal(active_id)
        if proposal.party:
            return proposal.party.id

    @classmethod
    def default_response_filename(cls):
        Proposal = Pool().get('gnuhealth.medical.purchase.procurement.proposal')
        active_id = Transaction().context.get('active_id')
        if not active_id:
            return
        proposal = Proposal(active_id)
        return proposal.response_filename


class UploadProcurementResponseWizard(Wizard):
    'Upload Procurement Response'
    __name__ = 'gnuhealth.medical.purchase.procurement.upload_response_wizard'

    start_state = 'start'
    start = StateView(
        'gnuhealth.medical.purchase.procurement.upload_response',
        'z_001_medical_purchase_procurement.'
        'view_upload_procurement_response_start',
        [
            Button('Cancelar', 'end', 'tryton-cancel'),
            Button('Guardar', 'save_response', 'tryton-ok', default=True),
        ])
    save_response = StateTransition()

    def transition_save_response(self):
        Proposal = Pool().get('gnuhealth.medical.purchase.procurement.proposal')
        Proposal._ensure_manager_for_buttons()
        active_id = Transaction().context.get('active_id')
        if not active_id:
            raise UserError('No se encontro la propuesta a actualizar.')
        if not self.start.response_file:
            raise UserError(
                'Debe seleccionar un archivo de respuesta del proveedor.')
        if not self.start.response_filename:
            raise UserError(
                'Debe indicar el nombre del archivo de respuesta.')
        proposal = Proposal(active_id)
        Proposal.write([proposal], {
            'response_filename': self.start.response_filename,
            'response_file': self.start.response_file,
        })
        return 'end'

    def end(self):
        return 'reload'


class StartProcurementRoundStart(ModelView):
    'Start Procurement Round Start'
    __name__ = 'gnuhealth.medical.purchase.procurement.start'

    audit_document = fields.Many2One(
        'gnuhealth.medical.purchase.audit', 'Documento', readonly=True)
    generated_name = fields.Char('Nombre de Ronda', readonly=True)
    party_lines = fields.One2Many(
        'gnuhealth.medical.purchase.procurement.start.party', None,
        'Proveedores')

    @classmethod
    def default_audit_document(cls):
        active_id = Transaction().context.get('active_id')
        if active_id:
            return active_id

    @classmethod
    def default_generated_name(cls):
        Audit = Pool().get('gnuhealth.medical.purchase.audit')
        active_id = Transaction().context.get('active_id')
        if not active_id:
            return
        audit = Audit(active_id)
        return MedicalPurchaseProcurementRound._build_round_name(audit)


class StartProcurementRoundParty(ModelView):
    'Start Procurement Round Party'
    __name__ = 'gnuhealth.medical.purchase.procurement.start.party'

    party = fields.Many2One('party.party', 'Proveedor', required=True)


class StartProcurementRoundWizard(Wizard):
    'Start Procurement Round'
    __name__ = 'gnuhealth.medical.purchase.procurement.start_wizard'

    start_state = 'start'
    start = StateView(
        'gnuhealth.medical.purchase.procurement.start',
        'z_001_medical_purchase_procurement.'
        'view_start_procurement_round_start',
        [
            Button('Cancelar', 'end', 'tryton-cancel'),
            Button('Confirmar', 'create_round', 'tryton-ok', default=True),
        ])
    create_round = StateTransition()

    def transition_create_round(self):
        pool = Pool()
        Audit = pool.get('gnuhealth.medical.purchase.audit')
        Round = pool.get('gnuhealth.medical.purchase.procurement.round')
        Round._ensure_procurement_manager()
        active_id = Transaction().context.get('active_id')
        if not active_id:
            raise UserError(
                'No se encontro un documento aceptado para iniciar '
                'procurement.')
        audit = Audit(active_id)
        Round._validate_audit_document(audit)
        Round._validate_no_active_round(audit)

        parties = []
        seen = set()
        for line in self.start.party_lines or []:
            if not line.party:
                continue
            if line.party.id in seen:
                raise UserError(
                    'No se puede repetir el mismo proveedor en la ronda.')
            seen.add(line.party.id)
            parties.append(line.party)
        if not parties:
            raise UserError(
                'Debe seleccionar al menos un proveedor.')

        proposal_values = [{'party': party.id} for party in parties]
        with Transaction().set_context(from_procurement_start_wizard=True):
            Round.create([{
                'audit_document': audit.id,
                'name': self.start.generated_name,
                'proposals': [('create', proposal_values)],
            }])
        return 'end'

    def end(self):
        return 'reload'


class SelectProcurementWinnerStart(ModelView):
    'Select Procurement Winner Start'
    __name__ = 'gnuhealth.medical.purchase.procurement.select_winner'

    round = fields.Many2One(
        'gnuhealth.medical.purchase.procurement.round', 'Ronda',
        readonly=True)
    proposal = fields.Many2One(
        'gnuhealth.medical.purchase.procurement.proposal', 'Propuesta',
        required=True,
        domain=[('round', '=', Eval('round', -1))], depends=['round'])

    @classmethod
    def default_round(cls):
        active_id = Transaction().context.get('active_id')
        if active_id:
            return active_id


class SelectProcurementWinnerWizard(Wizard):
    'Select Procurement Winner'
    __name__ = 'gnuhealth.medical.purchase.procurement.select_winner_wizard'

    start_state = 'start'
    start = StateView(
        'gnuhealth.medical.purchase.procurement.select_winner',
        'z_001_medical_purchase_procurement.'
        'view_select_procurement_winner_start',
        [
            Button('Cancelar', 'end', 'tryton-cancel'),
            Button('Confirmar', 'apply_winner', 'tryton-ok', default=True),
        ])
    apply_winner = StateTransition()

    def transition_apply_winner(self):
        pool = Pool()
        Round = pool.get('gnuhealth.medical.purchase.procurement.round')
        Proposal = pool.get('gnuhealth.medical.purchase.procurement.proposal')
        Round._ensure_procurement_manager()
        active_id = Transaction().context.get('active_id')
        if not active_id:
            raise UserError('No se encontro la ronda a procesar.')
        if not self.start.proposal:
            raise UserError('Debe seleccionar una propuesta ganadora.')
        round_ = Round(active_id)
        proposal = Proposal(self.start.proposal.id)
        Round.select_winner(round_, proposal)
        return 'end'

    def end(self):
        return 'reload'


class GenerateProcurementPurchaseStart(ModelView):
    'Generate Procurement Purchase Start'
    __name__ = 'gnuhealth.medical.purchase.procurement.generate_purchase'

    round = fields.Many2One(
        'gnuhealth.medical.purchase.procurement.round', 'Ronda',
        readonly=True)
    warehouse = fields.Many2One(
        'stock.location', 'Deposito',
        domain=[('type', '=', 'warehouse')])

    @classmethod
    def default_round(cls):
        active_id = Transaction().context.get('active_id')
        if active_id:
            return active_id

    @classmethod
    def default_warehouse(cls):
        Location = Pool().get('stock.location')
        return Location.get_default_warehouse()


class GenerateProcurementPurchaseWizard(Wizard):
    'Generate Procurement Purchase'
    __name__ = 'gnuhealth.medical.purchase.procurement.generate_purchase_wizard'

    start_state = 'start'
    start = StateView(
        'gnuhealth.medical.purchase.procurement.generate_purchase',
        'z_001_medical_purchase_procurement.'
        'view_generate_procurement_purchase_start',
        [
            Button('Cancelar', 'end', 'tryton-cancel'),
            Button('Confirmar', 'generate_purchase', 'tryton-ok', default=True),
        ])
    generate_purchase = StateTransition()

    def transition_generate_purchase(self):
        pool = Pool()
        Round = pool.get('gnuhealth.medical.purchase.procurement.round')
        Location = pool.get('stock.location')
        Round._ensure_procurement_manager()
        active_id = Transaction().context.get('active_id')
        if not active_id:
            raise UserError('No se encontro la ronda a procesar.')
        round_ = Round(active_id)
        warehouse = None
        if self.start.warehouse:
            warehouse = Location(self.start.warehouse.id)
        round_.generate_purchase(warehouse=warehouse)
        return 'end'

    def end(self):
        return 'reload'
