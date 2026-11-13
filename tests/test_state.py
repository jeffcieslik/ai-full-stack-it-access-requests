import json
from pathlib import Path
import tempfile

from support import FIXTURES, ROOT, OfflineTest


class StateTests(OfflineTest):
    def setUp(self):
        super().setUp()
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path=Path(self.directory.name)

    def resources(self):
        from it_access.core import load_source
        from it_access.providers import MockProvider
        from it_access.state import Store
        return Store(self.path/'state.db'), load_source(ROOT/'materials/requests/IT-001.json'), MockProvider(fixture_dir=FIXTURES)

    def test_unchanged_rerun(self):
        store,source,provider=self.resources()
        first=store.run(source,provider,{})
        second=store.run(source,provider,{})
        self.assertEqual(first['attempt_id'],second['attempt_id'])
        self.assertEqual(provider.call_count,1)
        self.assertEqual(len(store.current()),1)

    def test_changed_source(self):
        store,source,provider=self.resources()
        first=store.run(source,provider,{})
        from it_access.core import decode_source
        changed=decode_source(source.document_id,source.raw.replace(b'2026-11-06',b'2026-11-07'))
        # A saved revision reply changes exactly the explicitly edited date.
        from it_access.providers import MockProvider
        revised=MockProvider(fixture_dir=FIXTURES)
        original_complete=revised.complete
        def reply(**kwargs):
            result=original_complete(**kwargs)
            result.raw_response['choices'][0]['message']['content']=result.raw_response['choices'][0]['message']['content'].replace('2026-11-06','2026-11-07')
            return result
        revised.complete=reply
        result=store.run(changed,revised,{})
        self.assertNotEqual(result['source_sha256'],first['source_sha256'])
        self.assertEqual(result['extraction']['end_date'],'2026-11-07')
        self.assertEqual(len(store.history(source.document_id)),2)
        self.assertEqual(len(store.current()),1)

    def test_failed_retry_after_success(self):
        store,source,provider=self.resources()
        first=store.run(source,provider,{})
        from it_access.providers import MockProvider
        broken=MockProvider(fixture_dir=FIXTURES,before_response=lambda name:(_ for _ in ()).throw(TimeoutError('simulated')))
        failed=store.run(source,broken,{},force=True)
        self.assertEqual(store.current()[0]['status'],'error')
        self.assertIsNone(failed['extraction'])
        history=store.history(source.document_id)
        self.assertEqual(history[0]['record']['extraction'],first['extraction'])
        self.assertNotEqual(first['attempt_id'],failed['attempt_id'])
        self.assertIn(str(failed['attempt_id']),failed['retry_command'])

    def test_incremental_batches(self):
        store,source,provider=self.resources()
        from it_access.core import load_source
        other=load_source(ROOT/'materials/requests/IT-008.json')
        store.run(source,provider,{})
        store.run(other,provider,{})
        store.run(other,provider,{})
        self.assertEqual(len(store.current()),2)
        self.assertEqual(provider.call_count,2)
