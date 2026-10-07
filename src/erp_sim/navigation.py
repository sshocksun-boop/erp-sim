"""Shared login acceptance, frontend calls, menu navigation and safe logout."""
from .protocol.events import configure, action, function_return
from .protocol.handshake import announcements


def field_id(tree, name):
    matches = [i for i, n in tree.nodes.items() if n['kind'] == 'FormField'
               and n['attrs'].get('name') == 'formonly.' + name]
    return matches[-1] if matches else None


def active_action(tree, name):
    matches = [i for i, n in tree.nodes.items() if n['kind'] == 'Action'
               and n['attrs'].get('name') == name and n['attrs'].get('active') == '1']
    return matches[0] if len(matches) == 1 else None


def last_accept(tree):
    matches = [i for i, n in tree.nodes.items() if n['kind'] == 'Action'
               and n['attrs'].get('name') == 'accept']
    return matches[-1] if matches else None


def screen_role(tree):
    if field_id(tree, 'g_plant') is not None:
        return 'login'
    if field_id(tree, 'favorite_prog') is not None:
        return 'menu'
    return 'feature'


def account_binding_rejected(tree):
    return any('(azz-910)' in node['attrs'].get('text', '').lower()
               for node in tree.nodes.values())


class LoginFlow:
    def __init__(self):
        self.announced = False
        self.accepted = False

    def advance(self, channel):
        if not self.announced:
            for payload in announcements(['logo']):
                channel.send(payload)
            self.announced = True
        accept = last_accept(channel.tree)
        if not self.accepted and channel.quiet(1.5) and accept:
            channel.emit(action(accept))
            self.accepted = True


class MenuFlow:
    def __init__(self, program):
        self.program = program
        self.launched = False
        self.retried = False

    def advance(self, channel, feature_started):
        favorite = field_id(channel.tree, 'favorite_prog')
        accept = last_accept(channel.tree)
        if not favorite or not accept:
            return
        if not self.launched and channel.quiet(1.5):
            channel.emit(configure(favorite, cursor=0, cursor2=0))
            channel.emit(configure(favorite, value=self.program), action(accept))
            self.launched = True
        elif self.launched and not self.retried and not feature_started and channel.quiet(8):
            if channel.tree.nodes.get(0, {}).get('attrs', {}).get('focus') != str(favorite):
                channel.emit(configure(favorite, cursor=0, cursor2=0))
                channel.emit(action(accept))
                self.retried = True


class FrontendCalls:
    def __init__(self, hostname):
        self.hostname = hostname
        self.completed = set()

    def advance(self, channel):
        if not channel.quiet(0.5):
            return
        for ident, node in channel.tree.nodes.items():
            if node['kind'] != 'FunctionCall' or (channel.tag, ident) in self.completed:
                continue
            name = node['attrs'].get('name')
            params = [channel.tree.nodes[i]['attrs'].get('value', '') for i in node['children']]
            if name == 'getenv' and params == ['COMPUTERNAME']:
                channel.emit(function_return(self.hostname, 'STRING'))
            elif name == 'setwebcomponentpath':
                channel.emit(function_return('1', 'INTEGER'))
            else:
                continue
            self.completed.add((channel.tag, ident))


class LogoutFlow:
    def __init__(self):
        self.sent = set()

    def advance(self, channel):
        tree = channel.tree
        menus = [n for n in tree.nodes.values() if n['kind'] == 'Menu' and n['attrs'].get('active') == '1']
        if menus:
            options = [i for n in menus for i in n['children']
                       if tree.nodes[i]['kind'] == 'MenuAction'
                       and tree.nodes[i]['attrs'].get('name') == 'close_udmtree'
                       and tree.nodes[i]['attrs'].get('active') == '1']
            ident = options[0] if len(options) == 1 else None
        else:
            ident = next((i for name in ('exit', 'cancel', 'close')
                          if (i := active_action(tree, name)) is not None), None)
        if ident is not None and (channel.tag, ident) not in self.sent:
            channel.emit(action(ident))
            self.sent.add((channel.tag, ident))
