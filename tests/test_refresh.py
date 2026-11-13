from pathlib import Path
import tempfile

from support import FIXTURES, ROOT, OfflineTest


class RefreshTests(OfflineTest):
    def test_settings_refresh(self):
        from it_access.core import load_source
        from it_access.providers import MockProvider
        from it_access.state import Store
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'state.db')
            provider=MockProvider(fixture_dir=FIXTURES)
            source=load_source(ROOT/'materials/requests/IT-001.json')
            first=store.run(source,provider,{'model':'mock-a'})
            changed=store.run(source,provider,{'model':'mock-b'})
            self.assertEqual(provider.call_count,2)
            self.assertNotEqual(first['processing_settings']['extraction_fingerprint'],changed['processing_settings']['extraction_fingerprint'])
            self.assertEqual(first['source_sha256'],changed['source_sha256'])

    def test_policy_refresh(self):
        from it_access.core import load_source
        from it_access.providers import MockProvider
        from it_access.state import Store
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'state.db')
            provider=MockProvider(fixture_dir=FIXTURES)
            source=load_source(ROOT/'materials/requests/IT-001.json')
            first=store.run(source,provider,{'policy_version':'v1'})
            changed=store.run(source,provider,{'policy_version':'test-v2'},route_handler=lambda value:('review','Test Reviewer','review-request'))
            self.assertEqual(provider.call_count,1)
            self.assertEqual(changed['owner'],'Test Reviewer')
            self.assertEqual(changed['extraction_attempt_id'],first['attempt_id'])
            self.assertEqual(len(store.history(source.document_id)),2)
