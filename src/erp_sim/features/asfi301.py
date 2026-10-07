"""Create one asfi301 work order through a single, non-retryable submission."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

from ..errors import ErpError
from ..protocol.events import action, configure
from ..protocol.handshake import announcements


def key_tab():
    return '{KeyEvent 0{{keyName "Tab"}}}'


@dataclass(frozen=True)
class WorkOrderEntry:
    prefix: str
    department_vendor: str
    product: str
    quantity: int
    remark: str
    expected_manufacturing_department: str | None = None

    def __post_init__(self):
        if not all(isinstance(value, str) for value in (
                self.prefix, self.department_vendor, self.product, self.remark)):
            raise ErpError('INVALID_ARGUMENT', 'Work-order text fields must be strings')
        normalized = self.remark.replace('\r\n', '\n').replace('\r', '\n')
        object.__setattr__(self, 'remark', normalized)
        rules = (
            (self.prefix, r'[A-Z0-9]{5}', 'prefix'),
            (self.department_vendor, r'[A-Z0-9]{1,20}', 'department_vendor'),
            (self.product, r'[A-Z0-9_.-]{1,40}', 'product'),
        )
        for value, pattern, name in rules:
            if not re.fullmatch(pattern, value):
                raise ErpError('INVALID_ARGUMENT', f'Invalid {name}')
        if (self.expected_manufacturing_department is not None
                and (not isinstance(self.expected_manufacturing_department, str)
                     or not re.fullmatch(r'[A-Z0-9]{1,20}',
                                         self.expected_manufacturing_department))):
            raise ErpError('INVALID_ARGUMENT', 'Invalid expected_manufacturing_department')
        if (type(self.quantity) not in (int, float)
                or not 1 <= self.quantity <= 99_999_999
                or self.quantity != int(self.quantity)):
            raise ErpError('INVALID_ARGUMENT', 'quantity must be a positive integer within the form width')
        object.__setattr__(self, 'quantity', int(self.quantity))
        if not 1 <= len(normalized) <= 255 or any(ord(char) < 32 and char != '\n' for char in normalized):
            raise ErpError('INVALID_ARGUMENT', 'remark must be 1..255 characters and contain only text or LF newlines')

    def as_dict(self):
        result = {'prefix': self.prefix, 'department_vendor': self.department_vendor,
                  'product': self.product, 'quantity': self.quantity, 'remark': self.remark,
                  'operation': 'create_one', 'automatic_retry': False}
        if self.expected_manufacturing_department is not None:
            result['expected_manufacturing_department'] = self.expected_manufacturing_department
        return result


def unique_node(tree, kind, name, active=False):
    matches = [(ident, node) for ident, node in tree.nodes.items()
               if node['kind'] == kind and node['attrs'].get('name') == name
               and (not active or node['attrs'].get('active') == '1')]
    if len(matches) > 1:
        raise ErpError('PROTOCOL_ERROR', f'Ambiguous {kind} named {name}')
    return matches[0] if matches else (None, None)


def field_value(tree, name):
    _, node = unique_node(tree, 'FormField', name)
    return node['attrs'].get('value') if node else None


def focused(tree, name):
    ident, _ = unique_node(tree, 'FormField', name)
    return ident is not None and tree.nodes.get(0, {}).get('attrs', {}).get('focus') == str(ident)


def input_accept(tree):
    dialogs = [node for node in tree.nodes.values()
               if node['kind'] == 'Dialog' and node['attrs'].get('active') == '1'
               and any(tree.nodes[child]['kind'] == 'DialogInfo'
                       and tree.nodes[child]['attrs'].get('dialogType') == 'Input'
                       for child in node['children'])]
    if len(dialogs) != 1:
        return None
    matches = [child for child in dialogs[0]['children']
               if tree.nodes[child]['kind'] == 'Action'
               and tree.nodes[child]['attrs'].get('name') == 'accept'
               and tree.nodes[child]['attrs'].get('active') == '1']
    return matches[0] if len(matches) == 1 else None


def error_messages(tree):
    return [node['attrs'].get('text', '') for node in tree.nodes.values()
            if node['kind'] == 'Message' and node['attrs'].get('type') == 'error'
            and node['attrs'].get('text')]


def detail_page(tree):
    _, table = unique_node(tree, 'Table', 's_sfa')
    if table is None:
        raise ErpError('INCOMPLETE_RESULT', 'Main detail table is missing')
    try:
        total = int(table['attrs']['size'])
        offset = int(table['attrs']['offset'])
        page_size = int(table['attrs']['pageSize'])
    except (KeyError, ValueError):
        raise ErpError('PROTOCOL_ERROR', 'Main detail table range is invalid') from None
    if total < 0 or offset != 0 or page_size < 1:
        raise ErpError('INCOMPLETE_RESULT', 'Main detail table starts at an unsupported range')
    visible = min(total, page_size)
    columns = [tree.nodes[child] for child in table['children']
               if tree.nodes[child]['kind'] == 'TableColumn']
    if not columns:
        raise ErpError('INCOMPLETE_RESULT', 'Main detail table has no columns')
    for column in columns:
        lists = [tree.nodes[child] for child in column['children']
                 if tree.nodes[child]['kind'] == 'ValueList']
        if len(lists) != 1 or len(lists[0]['children']) < visible:
            raise ErpError('INCOMPLETE_RESULT', 'Visible detail page is truncated')
    return {'expected_row_count': total, 'visible_row_count': visible,
            'column_count': len(columns), 'complete': total == visible}


class Asfi301:
    program = 'asfi301'
    key_column = None
    warning_code = '(csf-a06)'

    def __init__(self, entry):
        self.entry = entry
        self.stage = 'initial'
        self.done = False
        self.result = None
        self.announced = set()
        self.child_seen = False
        self.child_confirmed = False

    def emit(self, channel, *commands):
        channel.emit(*commands)
        channel.touch()

    def advance(self, channel):
        tree = channel.tree
        program = tree.nodes.get(0, {}).get('attrs', {}).get('name')
        if program not in ('asfi301', 'asfp301'):
            return
        if channel.tag not in self.announced:
            for payload in announcements(['file_q', 'file_w']):
                channel.send(payload)
            self.announced.add(channel.tag)
        if program == 'asfp301':
            self.child_seen = True
            ident, node = unique_node(tree, 'MenuAction', 'ok', active=True)
            if (ident is not None and node is not None
                    and node['attrs'].get('text') == '确定'
                    and not self.child_confirmed):
                self.emit(channel, action(ident))
                self.child_confirmed = True
            return
        if self.done:
            return

        errors = error_messages(tree)
        if any(self.warning_code not in message for message in errors):
            raise ErpError('PROTOCOL_ERROR', 'ERP returned an unexpected form error')
        entry = self.entry
        if self.stage == 'initial':
            ident, _ = unique_node(tree, 'Action', 'insert', active=True)
            field, _ = unique_node(tree, 'FormField', 'sfb_file.sfb01')
            if ident is not None and field is not None:
                self.emit(channel, action(ident))
                self.stage = 'insert_sent'
        elif self.stage == 'insert_sent' and input_accept(tree) and focused(tree, 'sfb_file.sfb01'):
            if (field_value(tree, 'sfb_file.sfb01') or '').strip(' -'):
                raise ErpError('CONDITION_MISMATCH', 'Work-order form did not start with an empty identifier')
            ident, _ = unique_node(tree, 'FormField', 'sfb_file.sfb01')
            self.emit(channel, configure(ident, cursor=7, cursor2=6,
                                         value=entry.prefix + '-' + ' ' * 9), key_tab())
            self.stage = 'prefix_sent'
        elif self.stage == 'prefix_sent' and focused(tree, 'sfb_file.sfb44'):
            if field_value(tree, 'sfb_file.sfb01') != entry.prefix + '-':
                raise ErpError('CONDITION_MISMATCH', 'ERP changed the requested work-order prefix')
            self.emit(channel, key_tab()); self.stage = 'tab1'
        elif self.stage == 'tab1' and focused(tree, 'sfb_file.sfb81'):
            self.emit(channel, key_tab()); self.stage = 'tab2'
        elif self.stage == 'tab2' and focused(tree, 'sfb_file.sfb02'):
            self.emit(channel, key_tab()); self.stage = 'tab3'
        elif self.stage == 'tab3' and focused(tree, 'sfb_file.sfb39'):
            manufacturing_department = field_value(tree, 'formonly.ta_sfb06')
            if (not manufacturing_department
                    or not field_value(tree, 'formonly.ta_sfb06_name')
                    or (entry.expected_manufacturing_department is not None
                        and manufacturing_department != entry.expected_manufacturing_department)):
                raise ErpError('CONDITION_MISMATCH', 'Manufacturing department does not match the request')
            ident, _ = unique_node(tree, 'FormField', 'sfb_file.sfb82')
            self.emit(channel, configure(ident, cursor=len(entry.department_vendor),
                                         cursor2=len(entry.department_vendor)))
            self.stage = 'vendor_focused'
        elif self.stage == 'vendor_focused' and focused(tree, 'sfb_file.sfb82'):
            ident, _ = unique_node(tree, 'FormField', 'sfb_file.sfb82')
            self.emit(channel, configure(ident, value=entry.department_vendor), key_tab())
            self.stage = 'vendor_sent'
        elif self.stage == 'vendor_sent' and focused(tree, 'formonly.ta_sfb06'):
            if field_value(tree, 'sfb_file.sfb82') != entry.department_vendor or not field_value(tree, 'formonly.pmc03'):
                raise ErpError('CONDITION_MISMATCH', 'ERP did not validate department/vendor')
            ident, _ = unique_node(tree, 'FormField', 'sfb_file.sfb05')
            self.emit(channel, configure(ident, cursor=0, cursor2=0))
            self.stage = 'product_focused'
        elif self.stage == 'product_focused' and focused(tree, 'sfb_file.sfb05'):
            ident, _ = unique_node(tree, 'FormField', 'sfb_file.sfb05')
            self.emit(channel, configure(ident, cursor=len(entry.product), cursor2=len(entry.product),
                                         value=entry.product), key_tab())
            self.stage = 'product_sent'
        elif self.stage == 'product_sent' and focused(tree, 'sfb_file.sfb08'):
            if field_value(tree, 'sfb_file.sfb05') != entry.product or not field_value(tree, 'formonly.ima02'):
                raise ErpError('CONDITION_MISMATCH', 'ERP did not validate the product')
            ident, _ = unique_node(tree, 'FormField', 'sfb_file.sfb08')
            quantity = str(entry.quantity)
            self.emit(channel, configure(ident, cursor=len(quantity), cursor2=len(quantity),
                                         value=quantity), key_tab())
            self.stage = 'quantity_sent'
        elif self.stage == 'quantity_sent' and focused(tree, 'sfb_file.sfb07'):
            try:
                preserved = Decimal(field_value(tree, 'sfb_file.sfb08') or '') == entry.quantity
            except InvalidOperation:
                preserved = False
            if not preserved:
                raise ErpError('CONDITION_MISMATCH', 'ERP did not preserve production quantity')
            ident, _ = unique_node(tree, 'FormField', 'formonly.ta_sfb09')
            self.emit(channel, configure(ident, cursor=0, cursor2=0))
            self.stage = 'page2_focused'
        elif self.stage == 'page2_focused' and focused(tree, 'formonly.ta_sfb09'):
            ident, _ = unique_node(tree, 'FormField', 'sfb_file.sfb96')
            self.emit(channel, configure(ident, cursor=0, cursor2=0))
            self.stage = 'remark_focused'
        elif self.stage == 'remark_focused' and focused(tree, 'sfb_file.sfb96'):
            ident, _ = unique_node(tree, 'FormField', 'sfb_file.sfb96')
            accept = input_accept(tree)
            if accept is None:
                raise ErpError('PROTOCOL_ERROR', 'Entry confirmation is not active')
            self.result = {'status': 'uncertain', 'work_order_number': None,
                           'fields_verified': None, 'product_name': None,
                           'detail': None, 'warnings': [],
                           'persistence_readback': 'not_performed'}
            self.emit(channel, configure(ident, cursor=len(entry.remark), cursor2=len(entry.remark),
                                         value=entry.remark), action(accept))
            self.stage = 'submitted'
        elif self.stage == 'submitted':
            number = field_value(tree, 'sfb_file.sfb01')
            if number is None or not re.fullmatch(re.escape(entry.prefix) + r'-\d{9}', number):
                return
            if input_accept(tree) is not None or (self.child_seen and not self.child_confirmed):
                return
            observed = {'department_vendor': field_value(tree, 'sfb_file.sfb82'),
                        'department_vendor_name': field_value(tree, 'formonly.pmc03'),
                        'manufacturing_department': field_value(tree, 'formonly.ta_sfb06'),
                        'manufacturing_department_name': field_value(tree, 'formonly.ta_sfb06_name'),
                        'product': field_value(tree, 'sfb_file.sfb05'),
                        'quantity': field_value(tree, 'sfb_file.sfb08'),
                        'remark': field_value(tree, 'sfb_file.sfb96')}
            try:
                quantity_matches = Decimal(observed['quantity'] or '') == entry.quantity
            except InvalidOperation:
                quantity_matches = False
            if (observed['department_vendor'] != entry.department_vendor
                    or not observed['department_vendor_name']
                    or not observed['manufacturing_department']
                    or (entry.expected_manufacturing_department is not None
                        and observed['manufacturing_department'] != entry.expected_manufacturing_department)
                    or not observed['manufacturing_department_name']
                    or observed['product'] != entry.product or not quantity_matches
                    or observed['remark'] != entry.remark):
                raise ErpError('CONDITION_MISMATCH', 'Final ERP form does not match requested fields')
            self.result = {'status': 'server_confirmed', 'work_order_number': number,
                           'fields_verified': observed,
                           'product_name': field_value(tree, 'formonly.ima02'),
                           'detail': detail_page(tree),
                           'warnings': [{'code': 'csf-a06', 'message': message}
                                        for message in errors if self.warning_code in message],
                           'persistence_readback': 'not_performed'}
            self.done = True
