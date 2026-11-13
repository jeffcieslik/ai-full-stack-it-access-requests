from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile

from support import ROOT, FIXTURES, OfflineTest


class HandoverTests(OfflineTest):
    def invoke(self,*args):
        from it_access.cli import main
        output=io.StringIO()
        with redirect_stdout(output):
            code=main(list(args))
        self.assertEqual(code,0)
        return json.loads(output.getvalue())

    def test_documented_handover_workflow(self):
        readme=(ROOT/'README.md').read_text()
        for text in ['uv sync --locked','intake','queue','pending','history','retry','resume','accuracy','API_KEY','mock','src/']:
            self.assertIn(text,readme)
        with tempfile.TemporaryDirectory() as directory:
            state=str(Path(directory)/'intake.db');output=str(Path(directory)/'deliverables')
            self.invoke('intake','--input',str(ROOT/'materials/requests'),'--state',state,'--fixtures',str(FIXTURES))
            self.invoke('export','--state',state,'--output',output)
            self.assertEqual(self.invoke('verify-exports','--output',output)['verified_documents'],20)
            result=self.invoke('accuracy','--input',str(ROOT/'materials/requests'),'--input',str(ROOT/'tests/inputs'),'--fixtures',str(FIXTURES),'--expected',str(ROOT/'tests/expected.json'),'--output',str(Path(output)/'accuracy.md'))
            self.assertEqual((result['matched'],result['total']),(252,252))
            self.invoke('request-evidence','--input',str(ROOT/'materials/requests/IT-001.json'),'--output',str(Path(output)/'request-evidence.json'))

    def test_packaging_and_request_evidence(self):
        from it_access.providers import build_request
        from it_access.core import load_source
        evidence=json.loads((ROOT/'deliverables/request-evidence.json').read_text())
        self.assertEqual(evidence['body'],build_request(load_source(ROOT/'materials/requests/IT-001.json').message,evidence['body']['model']))
        self.assertEqual(evidence['headers']['Authorization'],'Bearer <redacted>')
        self.assertIn('not sent',evidence['observation'])
        self.assertEqual((ROOT/'src/it_access/snapshot.schema.json').read_bytes(),(ROOT/'snapshot.schema.json').read_bytes())
        self.assertTrue((ROOT/'uv.lock').is_file())
        self.assertIn('src/it_access',(ROOT/'pyproject.toml').read_text())
        for name in ['extractions.jsonl','queue.json','accuracy.md','verification.md']:
            self.assertTrue((ROOT/'deliverables'/name).is_file(),name)
