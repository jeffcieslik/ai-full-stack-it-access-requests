import copy
import hashlib
import json
from pathlib import Path
import tempfile

from support import OfflineTest, ROOT, extraction


class InputTests(OfflineTest):
    def test_schema_contract(self):
        from it_access.core import validate_extraction
        good = extraction()
        validate_extraction(good)
        for key in good:
            broken = copy.deepcopy(good)
            del broken[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_extraction(broken)
        for key, value in [('kind','approved'), ('permission','root'), ('environment','dev'), ('issues',None), ('supporting_quotes',[3]), ('request_id',True)]:
            broken = dict(good, **{key:value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_extraction(broken)
        with self.assertRaises(ValueError):
            validate_extraction(dict(good, extra=True))

    def test_export_source_boundary(self):
        from it_access.core import load_source
        original = ROOT / 'materials/requests/IT-001.json'
        source = load_source(original)
        self.assertEqual(source.source_sha256, hashlib.sha256(original.read_bytes()).hexdigest())
        self.assertEqual(source.message, json.loads(original.read_text())['message'])
        with tempfile.TemporaryDirectory() as directory:
            record = json.loads(original.read_text())
            record['exported_at'] = '2000-01-01T00:00:00Z'
            record['subject'] = 'not a request fact'
            record['message'] += ' filler' * (200-len(record['message'].split()))
            path = Path(directory)/original.name
            path.write_text(json.dumps(record))
            modified = load_source(path)
            self.assertEqual(len(modified.message.split()), 200)
            self.assertEqual(modified.metadata['subject'], record['subject'])
            self.assertNotEqual(modified.source_sha256, source.source_sha256)

    def test_document_identity(self):
        from it_access.core import load_source
        with tempfile.TemporaryDirectory() as directory:
            original = ROOT/'materials/requests/IT-016.json'
            other = Path(directory)/'FOLLOWUP.json'
            other.write_bytes(original.read_bytes())
            self.assertEqual(load_source(original).document_id, 'IT-016.json')
            self.assertEqual(load_source(other).document_id, 'FOLLOWUP.json')

    def test_quote_validation(self):
        from it_access.core import validate_extraction
        message=json.loads((ROOT/'materials/requests/IT-002.json').read_text())['message']
        good=extraction('it-002.json')
        validate_extraction(good, message)
        for quote in ['invented evidence', message.replace('\n','\\n'), message.upper()]:
            with self.assertRaises(ValueError):
                validate_extraction(dict(good, supporting_quotes=[quote]), message)
