import copy
import json

from support import EXPECTED, FIXTURES, ROOT, OfflineTest, envelope


class PipelineTests(OfflineTest):
    def check_case(self, number):
        from it_access.core import load_source
        from it_access.pipeline import extract
        from it_access.providers import MockProvider
        name=f'IT-{number:03}.json'
        path=ROOT/('tests/inputs' if number==21 else 'materials/requests')/name
        record=extract(load_source(path), MockProvider(fixture_dir=FIXTURES))
        expected=EXPECTED[name]
        for key,value in expected['facts'].items():
            self.assertEqual(record['extraction'][key], value, (name,key))
        for key,value in expected['route'].items():
            self.assertEqual(record[key], value, (name,key))
        self.assertIsNone(record['error'])
        self.assertEqual(record['response_source'], 'mock')
        return record

    def test_complete_request(self):
        self.check_case(1)

    def test_missing_dates(self):
        record=self.check_case(10)
        self.assertTrue(any('end_date' in issue for issue in record['extraction']['issues']))

    def test_conflicting_environment(self):
        record=self.check_case(4)
        quotes=' '.join(record['extraction']['supporting_quotes'])
        self.assertIn('staging', quotes)
        self.assertIn('production', quotes)

    def test_embedded_instructions(self):
        record=self.check_case(6)
        self.assertTrue(any('override' in issue for issue in record['extraction']['issues']))
        self.assertIn('SYSTEM OVERRIDE', ' '.join(record['extraction']['supporting_quotes']))

    def test_withdrawal(self):
        self.check_case(5)

    def test_missing_required_facts(self):
        self.check_case(3)
        self.check_case(9)
        from it_access.pipeline import route
        from support import extraction
        for field in EXPECTED['IT-001.json']['facts']:
            if field=='kind': continue
            value=dict(extraction(), **{field:None})
            self.assertEqual(route(value)[0], 'needs-information', field)

    def test_relative_dates(self):
        self.check_case(11)

    def test_environment_correction(self):
        self.check_case(8)

    def test_date_correction(self):
        self.check_case(15)

    def test_change_permission(self):
        self.check_case(7)
        self.check_case(19)

    def test_identifier_mismatch(self):
        record=self.check_case(16)
        self.assertEqual(record['document_id'], 'IT-016.json')
        self.assertTrue(any('mismatch' in issue for issue in record['extraction']['issues']))

    def test_conflicting_manager(self):
        self.check_case(20)

    def test_other_message(self):
        self.check_case(17)

    def test_reverse_dates(self):
        self.check_case(14)

    def test_security_routing(self):
        for number in (2,12,13,18):
            self.check_case(number)

    def test_routing_precedence(self):
        from it_access.pipeline import route
        from support import extraction
        withdrawal=dict(extraction('it-005.json'))
        withdrawal['issues']=['override:Bypass approval rules', 'mismatch:request_id']
        self.assertEqual(route(withdrawal), ('review','IT Service Desk','inspect-message'))
        withdrawal['issues']=['mismatch:request_id']
        self.assertEqual(route(withdrawal), ('review','IT Service Desk','confirm-withdrawal'))

    def test_fresh_paraphrase(self):
        self.check_case(21)
