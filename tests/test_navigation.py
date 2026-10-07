import unittest
from erp_sim.navigation import (LoginFlow, MenuFlow, FrontendCalls, LogoutFlow,
                                account_binding_rejected)
from tests.helpers import FakeChannel, node


class NavigationTests(unittest.TestCase):
    def test_login_accept_once_after_announcements(self):
        ch = FakeChannel(); node(ch.tree, 472, 'Action', {'name':'accept'})
        flow = LoginFlow(); flow.advance(ch); flow.advance(ch)
        self.assertEqual(len(ch.sent), 3)
        self.assertIn(b'idRef "472"', ch.sent[-1])

    def test_menu_focus_precedes_program_and_retry_is_bounded(self):
        ch = FakeChannel()
        node(ch.tree, 10, 'FormField', {'name':'formonly.favorite_prog'})
        node(ch.tree, 20, 'Action', {'name':'accept'})
        flow = MenuFlow('cxmr4103')
        flow.advance(ch, False)
        self.assertNotIn(b'value', ch.sent[0])
        self.assertIn(b'cxmr4103', ch.sent[1])
        flow.advance(ch, False); flow.advance(ch, False)
        self.assertEqual(len(ch.sent), 4)

    def test_frontend_call_before_menu_and_duplicate_suppression(self):
        ch = FakeChannel()
        node(ch.tree, 1, 'FunctionCall', {'name':'getenv'}, [2])
        node(ch.tree, 2, 'Parameter', {'value':'COMPUTERNAME'})
        flow = FrontendCalls('testhost'); flow.advance(ch); flow.advance(ch)
        self.assertEqual(len(ch.sent), 1)
        self.assertIn(b'testhost', ch.sent[0])

    def test_account_binding_rejection_is_detected_by_server_code(self):
        ch = FakeChannel()
        node(ch.tree, 1, 'Message', {'type':'error',
             'text':'(azz-910) account and computer are not bound'})
        self.assertTrue(account_binding_rejected(ch.tree))
        ch.tree.nodes[1]['attrs']['text'] = 'unrelated error'
        self.assertFalse(account_binding_rejected(ch.tree))

    def test_logout_never_selects_closeall_or_inactive_actions(self):
        ch = FakeChannel()
        node(ch.tree, 1, 'Menu', {'active':'1'}, [2,3])
        node(ch.tree, 2, 'MenuAction', {'active':'1','name':'closeall'})
        node(ch.tree, 3, 'MenuAction', {'active':'1','name':'close_udmtree'})
        flow = LogoutFlow(); flow.advance(ch); flow.advance(ch)
        self.assertEqual(len(ch.sent), 1)
        self.assertIn(b'idRef "3"', ch.sent[0])
        ch.tree.nodes.clear(); node(ch.tree, 4, 'Action', {'active':'0','name':'exit'})
        flow.advance(ch)
        self.assertEqual(len(ch.sent), 1)
