# SPDX-FileCopyrightText: 2026 Custom GNU Health
# SPDX-License-Identifier: GPL-3.0-or-later

from datetime import datetime
from decimal import Decimal

from trytond.exceptions import UserError
from trytond.model import ModelSQL, ModelView, Unique, fields
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Bool, Eval, Not
from trytond.transaction import Transaction
from trytond.wizard import Button, StateTransition, StateView, Wizard

__all__ = [
    'MedicalPurchaseAudit',
    'MedicalPurchaseProcurementRound',
    'MedicalPurchaseProcurementProposal',
    'MedicalPurchaseProcurementProposalLine',
    'StartProcurementRoundStart',
    'StartProcurementRoundParty',
    'StartProcurementRoundWizard',
    'SelectProcurementWinnerStart',
    'SelectProcurementWinnerWizard',
    'GenerateProcurementPurchaseStart',
    'GenerateProcurementPurchaseWizard',
]

ZERO = Decimal('0.00')
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
    total_amount = fields.Function(
        fields.Numeric('Total Ganador', digits=(16, 2)),
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
            elif name == 'total_amount':
                result[record.id] = (
                    record.winner_proposal.total
                    if record.winner_proposal else ZERO)
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
                    raise UserError(
                        'La ronda ya no se puede modificar.')
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
        return (
            'Origen: %s | Ronda: %s'
            % (self.audit_document.rec_name, self.rec_name))

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
        for proposal_line in proposal.lines:
            proposal_line.validate_for_winner()
            line = PurchaseLine()
            line.purchase = purchase
            line.type = 'line'
            line.product = proposal_line.product
            line.quantity = float(proposal_line.quantity)
            line.on_change_product()
            line.unit_price = proposal_line.unit_price
            line.description = proposal_line.get_purchase_line_description()
            if not line.unit:
                raise UserError(
                    'El producto "%s" no tiene unidad de compra valida.'
                    % proposal_line.product.rec_name)
            lines.append(line)
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
            if round_.state == 'cancelled':
                continue
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
    total = fields.Function(
        fields.Numeric('Total', digits=(16, 2)), 'get_total')
    observations = fields.Text(
        'Observaciones',
        states={'readonly': Eval('round_state') != 'in_comparison'},
        depends=['round_state'])
    is_winner = fields.Boolean('Ganadora', readonly=True)
    purchase = fields.Many2One(
        'purchase.purchase', 'Compra Vinculada', readonly=True)
    lines = fields.One2Many(
        'gnuhealth.medical.purchase.procurement.proposal.line', 'proposal',
        'Lineas',
        states={'readonly': Eval('round_state') != 'in_comparison'},
        depends=['round_state'])
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
    def get_total(cls, records, name):
        return {
            record.id: sum(
                (line.subtotal or ZERO) for line in record.lines
            ) if record.lines else ZERO
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
        for records, values in zip(actions, actions):
            changed = set(values.keys())
            for record in records:
                if record.round.state != 'in_comparison' and changed - {
                        'is_winner', 'state', 'purchase'}:
                    raise UserError(
                        'La propuesta ya no se puede editar fuera de la '
                        'etapa de comparacion.')
                if changed & {'is_winner', 'state', 'purchase'} and not system_change:
                    raise UserError(
                        'La propuesta solo puede cambiar de estado desde las '
                        'acciones autorizadas.')
        super().write(*args)

    def validate_as_winner(self):
        if not self.lines:
            raise UserError(
                'La propuesta seleccionada no tiene lineas.')
        for line in self.lines:
            line.validate_for_winner()


class MedicalPurchaseProcurementProposalLine(ModelSQL, ModelView):
    'Medical Purchase Procurement Proposal Line'
    __name__ = 'gnuhealth.medical.purchase.procurement.proposal.line'

    proposal = fields.Many2One(
        'gnuhealth.medical.purchase.procurement.proposal', 'Propuesta',
        required=True, readonly=True, ondelete='CASCADE')
    medicament = fields.Many2One(
        'gnuhealth.medicament', 'Medicamento',
        required=True, readonly=True, ondelete='RESTRICT')
    product = fields.Many2One(
        'product.product', 'Producto',
        required=True, readonly=True, ondelete='RESTRICT')
    quantity = fields.Integer(
        'Cantidad',
        states={'readonly': Eval('proposal_round_state') != 'in_comparison'},
        depends=['proposal_round_state'])
    unit_price = fields.Numeric(
        'Precio Unitario', digits=(16, 2),
        states={'readonly': Eval('proposal_round_state') != 'in_comparison'},
        depends=['proposal_round_state'])
    subtotal = fields.Function(
        fields.Numeric('Subtotal', digits=(16, 2)),
        'get_subtotal')
    observations = fields.Text(
        'Observaciones',
        states={'readonly': Eval('proposal_round_state') != 'in_comparison'},
        depends=['proposal_round_state'])
    proposal_round_state = fields.Function(
        fields.Selection([
            ('draft', 'Borrador'),
            ('in_comparison', 'En Comparacion'),
            ('winner_selected', 'Ganador Seleccionado'),
            ('purchase_created', 'Compra Generada'),
            ('done', 'Finalizada'),
            ('cancelled', 'Cancelada'),
        ], 'Estado Ronda'),
        'get_proposal_round_state')

    @classmethod
    def get_proposal_round_state(cls, records, name):
        return {
            record.id: (
                record.proposal.round.state
                if record.proposal and record.proposal.round else None)
            for record in records
        }

    def _calculate_subtotal(self):
        quantity = Decimal(str(self.quantity or 0))
        price = self.unit_price if self.unit_price is not None else ZERO
        return price * quantity

    @classmethod
    def get_subtotal(cls, records, name):
        return {
            record.id: record._calculate_subtotal()
            for record in records
        }

    @fields.depends('quantity', 'unit_price')
    def on_change_with_subtotal(self, name=None):
        return self._calculate_subtotal()

    @classmethod
    def create(cls, vlist):
        if not Transaction().context.get('from_procurement_start_wizard'):
            raise UserError(
                'Las lineas de propuesta solo se pueden crear desde el '
                'wizard de inicio de ronda.')
        cls._validate_values(vlist)
        return super().create(vlist)

    @classmethod
    def write(cls, *args):
        actions = iter(args)
        for records, values in zip(actions, actions):
            cls._validate_values([values], records=records)
            for record in records:
                if record.proposal.round.state != 'in_comparison':
                    raise UserError(
                        'Las lineas solo se pueden editar durante la '
                        'comparacion.')
        super().write(*args)

    @classmethod
    def delete(cls, records):
        raise UserError(
            'Las lineas de propuesta no se pueden eliminar desde la interfaz.')

    @classmethod
    def validate(cls, records):
        super().validate(records)
        cls._validate_values([{
            'quantity': record.quantity,
            'unit_price': record.unit_price,
        } for record in records])

    @classmethod
    def _validate_values(cls, vlist, records=None):
        if records:
            for record in records:
                quantity = vlist[0].get('quantity', record.quantity)
                unit_price = vlist[0].get('unit_price', record.unit_price)
                if quantity is not None and quantity < 0:
                    raise UserError(
                        'La cantidad cotizada no puede ser menor que cero.')
                if unit_price is not None and unit_price < ZERO:
                    raise UserError(
                        'El precio unitario no puede ser menor que cero.')
            return
        for values in vlist:
            quantity = values.get('quantity')
            unit_price = values.get('unit_price')
            if quantity is not None and quantity < 0:
                raise UserError(
                    'La cantidad cotizada no puede ser menor que cero.')
            if unit_price is not None and unit_price < ZERO:
                raise UserError(
                    'El precio unitario no puede ser menor que cero.')

    def validate_for_winner(self):
        if self.quantity is None or self.quantity < 0:
            raise UserError(
                'La propuesta ganadora tiene cantidades invalidas.')
        if self.unit_price is None:
            raise UserError(
                'La propuesta ganadora debe tener todos los precios cargados.')
        if self.unit_price < ZERO:
            raise UserError(
                'La propuesta ganadora tiene precios negativos.')
        if not self.product.purchasable:
            raise UserError(
                'El producto "%s" no esta habilitado para compras.'
                % self.product.rec_name)

    def get_purchase_line_description(self):
        return '%s - Documento %s' % (
            self.medicament.rec_name, self.proposal.round.audit_document.rec_name)


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

        proposal_values = []
        for party in parties:
            line_values = []
            for audit_line in audit.lines:
                if not audit_line.medicament:
                    raise UserError(
                        'El documento aceptado contiene una linea sin '
                        'medicamento.')
                product = audit_line.medicament.name
                if not product:
                    raise UserError(
                        'El medicamento "%s" no tiene un producto asociado.'
                        % audit_line.medicament.rec_name)
                line_values.append({
                    'medicament': audit_line.medicament.id,
                    'product': product.id,
                    'quantity': audit_line.purchase_quantity,
                    'observations': None,
                })
            proposal_values.append({
                'party': party.id,
                'lines': [('create', line_values)],
            })

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
