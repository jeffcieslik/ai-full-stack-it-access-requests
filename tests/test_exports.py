import json
from pathlib import Path
import tempfile

from support import ROOT, FIXTURES, OfflineTest


class ExportTests(OfflineTest):
    def test_consistent_exports(self):
        from it_access.exporting import export_current,read_exports
        from it_access.state import Store
        from it_access.core import load_source,validate_extraction
        from it_access.providers import MockProvider
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'state.db')
            provider=MockProvider(fixture_dir=FIXTURES)
            for path in sorted((ROOT/'materials/requests').glob('*.json')):
                store.run(load_source(path),provider,{})
            target=Path(directory)/'deliverables'
            export_current(store,target)
            records,queue=read_exports(target)
            self.assertEqual(len(records),20)
            self.assertEqual({r['document_id'] for r in records},{p.name for p in (ROOT/'materials/requests').glob('*.json')})
            for record,item in zip(records,queue):
                validate_extraction(record['extraction'])
                self.assertEqual(item['attempt_id'],record['attempt_id'])
                self.assertEqual(item['source_sha256'],record['source_sha256'])
                self.assertIsNone(record['error'])
            (target/'.incomplete').write_text('simulated interrupted export')
            with self.assertRaises(ValueError):read_exports(target)
            export_current(store,target)
            self.assertEqual(len(read_exports(target)[0]),20)
            (target/'queue.json').write_text('[]')
            with self.assertRaises(ValueError):read_exports(target)
