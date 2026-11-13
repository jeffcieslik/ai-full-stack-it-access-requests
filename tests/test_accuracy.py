import copy
import json

from support import EXPECTED, ROOT, FIXTURES, OfflineTest


class AccuracyTests(OfflineTest):
    def test_independent_accuracy_comparison(self):
        from it_access.accuracy import compare
        from it_access.core import load_source
        from it_access.pipeline import extract
        from it_access.providers import MockProvider
        provider=MockProvider(fixture_dir=FIXTURES)
        records=[]
        for name in EXPECTED:
            path=ROOT/('tests/inputs' if name=='IT-021.json' else 'materials/requests')/name
            records.append(extract(load_source(path),provider))
        result=compare(records,EXPECTED)
        self.assertEqual((result['matched'],result['total']),(252,252))
        self.assertEqual(result['routing_matches'],21)
        self.assertEqual(result['quote_errors'],[])
        changed=copy.deepcopy(records)
        changed[0]['extraction']['requester']='Wrong Person'
        self.assertEqual(compare(changed,EXPECTED)['matched'],251)
        changed[0]['extraction']=None
        changed[0]['status']='error'
        result=compare(changed,EXPECTED)
        self.assertEqual((result['matched'],result['total']),(240,252))
        self.assertEqual(len(result['differences']),12)
        self.assertEqual(compare(records[:-1],EXPECTED)['total'],252)
        malformed=copy.deepcopy(records)
        malformed[0]['extraction']='not an extraction object'
        self.assertEqual(compare(malformed,EXPECTED)['matched'],240)
        malformed[0]['extraction']=dict(records[0]['extraction'],supporting_quotes=[5],issues=None)
        invalid=compare(malformed,EXPECTED)
        self.assertTrue(invalid['schema_errors'])
        self.assertIn('IT-001.json',invalid['quote_errors'])
