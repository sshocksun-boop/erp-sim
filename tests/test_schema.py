from copy import deepcopy
from datetime import datetime, timedelta
from importlib.resources import files
import json
import unittest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from erp_sim.cli import envelope
from erp_sim.errors import ErpError, EXIT_CODES
from erp_sim.features.abmr001 import BomQuery
from erp_sim.features.aimq102 import StockQuery
from erp_sim.features.aimq131 import ItemQuery
from erp_sim.features.aimq136 import WipQuery
from erp_sim.features.asfi301 import WorkOrderEntry
from tests.test_feature import QUERY


class SchemaTests(unittest.TestCase):
    def setUp(self):
        schema = json.loads(files('erp_sim.resources').joinpath('result.schema.json').read_text())
        Draft202012Validator.check_schema(schema)
        self.assertEqual(
            (schema['title'], schema['properties']['schema_version']['const'],
             schema['properties']['command']['const']),
            ('erp-sim cxmr4103 response v2', '2', 'cxmr4103'))
        self.validator = Draft202012Validator(schema, format_checker=FormatChecker())

    def success(self):
        doc = envelope(QUERY.as_dict())
        doc.update(ok=True, session={'logout_verified':True}, data={
            'columns':[{'id':'oea01_1','label':'订单单号'}], 'rows':[{'oea01_1':'S1702-001'}],
            'row_count':1,'expected_row_count':1,'order_count':1,'complete':True})
        return doc

    def test_valid_result_and_all_error_envelopes(self):
        self.validator.validate(self.success())
        for code in EXIT_CODES:
            doc = envelope()
            doc['error'] = ErpError(code, 'Test failure').as_dict()
            self.validator.validate(doc)

    def test_response_timestamp_uses_utc_plus_eight(self):
        timestamp = datetime.fromisoformat(envelope()['queried_at'])
        self.assertEqual(timestamp.utcoffset(), timedelta(hours=8))

    def test_success_cannot_hide_partial_data_failed_logout_or_error(self):
        mutations = [('data','complete',False),('session','logout_verified',False)]
        for section,key,value in mutations:
            doc=self.success();doc[section][key]=value
            with self.assertRaises(ValidationError):self.validator.validate(doc)
        doc=self.success();doc['error']={'code':'TIMEOUT','message':'Test'}
        with self.assertRaises(ValidationError):self.validator.validate(doc)

    def test_cell_values_preserve_strings_and_dates_are_validated(self):
        doc=self.success();doc['data']['rows'][0]['oea01_1']=123
        with self.assertRaises(ValidationError):self.validator.validate(doc)
        doc=self.success();doc['query']['date_from']='2026-02-30'
        with self.assertRaises(ValidationError):self.validator.validate(doc)


class Abmr001SchemaTests(unittest.TestCase):
    def setUp(self):
        schema = json.loads(files('erp_sim.resources').joinpath('abmr001.schema.json').read_text())
        Draft202012Validator.check_schema(schema)
        self.assertEqual(
            (schema['title'], schema['properties']['schema_version']['const'],
             schema['properties']['command']['const']),
            ('erp-sim abmr001 response v2', '2', 'abmr001'))
        self.validator = Draft202012Validator(schema, format_checker=FormatChecker())

    def success(self):
        doc = envelope(BomQuery('ROOT-001').as_dict(), 'abmr001')
        doc.update(ok=True, session={'logout_verified':True}, data={
            'item':'ROOT-001','description':'Root','effective_date':'26/09/15',
            'report_created_at':'26/09/15 16:00:00','version':'','sort':'bom_sequence',
            'component_count':1,'components':[{
                'level':1,'parent_item':'ROOT-001','sequence':'0010','component_item':'COMP-A',
                'component_type':'P','unit':'PCS','source':'1','description':'Part','marker':'*',
                'quantity_numerator':None,'quantity':'1.000','drawing':'MISC',
                'conversion_unit':'PCS','conversion':'1.000000','notes':[],
            }],'complete':True})
        return doc

    def test_valid_success_and_all_error_envelopes(self):
        self.validator.validate(self.success())
        for code in EXIT_CODES:
            doc=envelope(command='abmr001')
            doc['error']=ErpError(code,'Test failure').as_dict()
            self.validator.validate(doc)

    def test_success_requires_complete_data_logout_and_string_numbers(self):
        for section,key,value in [('data','complete',False),('session','logout_verified',False)]:
            doc=self.success();doc[section][key]=value
            with self.assertRaises(ValidationError):self.validator.validate(doc)
        doc=self.success();doc['data']['components'][0]['quantity']=1
        with self.assertRaises(ValidationError):self.validator.validate(doc)


class Aimq131SchemaTests(unittest.TestCase):
    def setUp(self):
        schema = json.loads(files('erp_sim.resources').joinpath('aimq131.schema.json').read_text())
        Draft202012Validator.check_schema(schema)
        self.validator = Draft202012Validator(schema, format_checker=FormatChecker())

    def success(self):
        doc = envelope(ItemQuery('ITEM-001').as_dict(), 'aimq131')
        doc.update(ok=True, session={'logout_verified': True}, data={
            'item': 'ITEM-001', 'description': 'Synthetic item', 'specification': '230V',
            'columns': [{'id': 'oeb01', 'label': '订单单号'},
                        {'id': 'oeb12', 'label': '受订量'}],
            'rows': [{'oeb01': 'ORDER-001', 'oeb12': '10.000'}],
            'row_count': 1, 'expected_row_count': 1, 'order_count': 1,
            'ordered_quantity_total': '10.000', 'open_quantity_total': '2.000',
            'complete': True,
        })
        return doc

    def test_success_and_errors(self):
        self.validator.validate(self.success())
        for code in EXIT_CODES:
            doc = envelope(command='aimq131')
            doc['error'] = ErpError(code, 'Test failure').as_dict()
            self.validator.validate(doc)

    def test_success_requires_complete_data_and_logout(self):
        for section, key, value in [('data', 'complete', False),
                                    ('session', 'logout_verified', False),
                                    ('data', 'ordered_quantity_total', 10)]:
            doc = self.success()
            doc[section][key] = value
            with self.subTest(section=section, key=key), self.assertRaises(ValidationError):
                self.validator.validate(doc)


class Aimq102SchemaTests(unittest.TestCase):
    def setUp(self):
        schema = json.loads(files('erp_sim.resources').joinpath('aimq102.schema.json').read_text())
        Draft202012Validator.check_schema(schema)
        self.assertEqual(
            (schema['title'], schema['properties']['schema_version']['const'],
             schema['properties']['command']['const']),
            ('erp-sim aimq102 response v2', '2', 'aimq102'))
        self.validator = Draft202012Validator(schema, format_checker=FormatChecker())

    def success(self):
        doc = envelope(StockQuery('ITEM-001').as_dict(), 'aimq102')
        quantities = {key: '10.000' for key in (
            'available_stock', 'ordered_qty', 'wo_material_prepared',
            'wo_material_short', 'purchase_request_qty', 'purchase_order_qty',
            'wo_in_process', 'subcontract_in_process', 'subcontract_iqc_inspect',
            'iqc_inspect', 'fqc_inspect', 'projected_available_header',
            'projected_available_table', 'unavailable_stock', 'setup_qty')}
        doc.update(ok=True, session={'logout_verified': True}, data={
            'item': 'ITEM-001', 'description': 'Synthetic item', 'specification': '230V',
            'current_version': '', 'group_code': '1000', 'stock_unit': 'PCS',
            'source_code': 'P', 'replenish_code': '2', 'unit_policy': '',
            'second_unit': '', 'consumable': 'N', 'bonded': 'N',
            **quantities,
            'columns': [{'id': 'img02', 'label': '仓库'},
                        {'id': 'img10', 'label': '库存数量'}],
            'rows': [{'img02': 'WH-001', 'img10': '10.000'}],
            'row_count': 1, 'expected_row_count': 1, 'warehouse_count': 1,
            'complete': True,
        })
        return doc

    def test_success_and_errors(self):
        self.validator.validate(self.success())
        for code in EXIT_CODES:
            doc = envelope(command='aimq102')
            doc['error'] = ErpError(code, 'Test failure').as_dict()
            self.validator.validate(doc)

    def test_success_requires_complete_data_and_string_numbers(self):
        for section, key, value in [('data', 'complete', False),
                                    ('session', 'logout_verified', False),
                                    ('data', 'available_stock', 10),
                                    ('data', 'projected_available_table', 9)]:
            doc = self.success()
            doc[section][key] = value
            with self.subTest(section=section, key=key), self.assertRaises(ValidationError):
                self.validator.validate(doc)


class Aimq136SchemaTests(unittest.TestCase):
    def setUp(self):
        schema = json.loads(files('erp_sim.resources').joinpath('aimq136.schema.json').read_text())
        Draft202012Validator.check_schema(schema)
        self.assertEqual(
            (schema['title'], schema['properties']['schema_version']['const'],
             schema['properties']['command']['const']),
            ('erp-sim aimq136 response v2', '2', 'aimq136'))
        self.validator = Draft202012Validator(schema, format_checker=FormatChecker())

    def success(self):
        doc = envelope(WipQuery('ITEM-001').as_dict(), 'aimq136')
        doc.update(ok=True, session={'logout_verified': True}, data={
            'item': 'ITEM-001', 'description': 'Synthetic item', 'specification': '230V',
            'source_code': 'P',
            'production_qty_total': '30.000', 'wo_in_process_total': '20.000',
            'subcontract_in_process_total': '0.000',
            'columns': [{'id': 'sfb01', 'label': '工单单号'},
                        {'id': 'woo_qty', 'label': '工单在制量'}],
            'rows': [{'sfb01': 'WO-001', 'woo_qty': '20.000'}],
            'row_count': 1, 'expected_row_count': 1, 'work_order_count': 1,
            'complete': True,
        })
        return doc

    def test_success_and_errors(self):
        self.validator.validate(self.success())
        for code in EXIT_CODES:
            doc = envelope(command='aimq136')
            doc['error'] = ErpError(code, 'Test failure').as_dict()
            self.validator.validate(doc)

    def test_success_requires_complete_data_and_string_numbers(self):
        for section, key, value in [('data', 'complete', False),
                                    ('session', 'logout_verified', False),
                                    ('data', 'wo_in_process_total', 20),
                                    ('data', 'work_order_count', '1')]:
            doc = self.success()
            doc[section][key] = value
            with self.subTest(section=section, key=key), self.assertRaises(ValidationError):
                self.validator.validate(doc)


class Asfi301SchemaTests(unittest.TestCase):
    def setUp(self):
        schema = json.loads(files('erp_sim.resources').joinpath('asfi301.schema.json').read_text())
        Draft202012Validator.check_schema(schema)
        self.assertEqual(
            (schema['title'], schema['properties']['schema_version']['const'],
             schema['properties']['command']['const']),
            ('erp-sim asfi301 response v2', '2', 'asfi301'))
        self.validator = Draft202012Validator(schema, format_checker=FormatChecker())
        self.entry = WorkOrderEntry('TST01', 'V001', 'ITEM-001', 42,
                                    'first line\nsecond line', 'D001')

    def success(self):
        doc = envelope(self.entry.as_dict(), 'asfi301')
        doc.update(ok=True, session={'logout_verified':True}, data={
            'status':'server_confirmed', 'work_order_number':'TST01-123456789',
            'fields_verified': {'department_vendor':'V001',
                'department_vendor_name':'Synthetic vendor',
                'manufacturing_department':'D001',
                'manufacturing_department_name':'Synthetic factory',
                'product':'ITEM-001', 'quantity':'42.000',
                'remark':'first line\nsecond line'},
            'product_name':'Synthetic product',
            'detail': {'expected_row_count':26, 'visible_row_count':10,
                       'column_count':50, 'complete':False},
            'warnings':[], 'persistence_readback':'not_performed'})
        return doc

    def test_valid_server_confirmed_success(self):
        self.validator.validate(self.success())

    def test_success_requires_number_fields_logout_and_server_confirmation(self):
        for section, key, value in [
                ('data','status','uncertain'), ('data','work_order_number',None),
                ('data','fields_verified',None), ('session','logout_verified',False)]:
            doc = self.success(); doc[section][key] = value
            with self.subTest(section=section, key=key), self.assertRaises(ValidationError):
                self.validator.validate(doc)

    def test_uncertain_write_is_valid_only_as_failure(self):
        doc = envelope(self.entry.as_dict(), 'asfi301')
        doc.update(data={'status':'uncertain', 'work_order_number':None,
                         'fields_verified':None, 'product_name':None, 'detail':None,
                         'warnings':[], 'persistence_readback':'not_performed'},
                   error=ErpError('TIMEOUT', 'Result unknown').as_dict())
        self.validator.validate(doc)
        doc['ok'] = True
        with self.assertRaises(ValidationError):
            self.validator.validate(doc)
