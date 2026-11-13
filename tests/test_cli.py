from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import shlex
import sys

from support import FIXTURES, ROOT, OfflineTest


class CLITests(OfflineTest):
    def invoke(self, *args):
        from it_access.cli import main
        output=io.StringIO()
        with redirect_stdout(output):
            code=main(list(args))
        self.assertEqual(code,0,output.getvalue())
        return json.loads(output.getvalue())

    def test_cli_intake_inspect_retry_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            state=str(Path(directory)/'state.db')
            queued=self.invoke('intake','--input',str(ROOT/'materials/requests'),'--state',state,'--fixtures',str(FIXTURES),'--enqueue-only')
            self.assertEqual(queued['registered_documents'],20)
            self.assertEqual(len(self.invoke('pending','--state',state)),20)
            self.invoke('resume','--state',state,'--rate-per-minute','0')
            queue=self.invoke('queue','--state',state)
            self.assertEqual(len(queue),20)
            self.assertEqual(queue[0]['owner'],'System Owner')
            history=self.invoke('history','--state',state,'--document','IT-001.json')
            self.assertEqual(history[0]['record']['extraction']['requester'],'Maya Chen')
            self.invoke('retry','--state',state,'--attempt',str(queue[0]['attempt_id']),'--rate-per-minute','0')
            self.assertEqual(len(self.invoke('queue','--state',state)),20)
            from it_access.state import Store
            from it_access.core import load_source
            from it_access.providers import MockProvider
            store=Store(state)
            failed=store.run(load_source(ROOT/'materials/requests/IT-001.json'),
                MockProvider(fixture_dir=FIXTURES,before_response=lambda name:(_ for _ in ()).throw(TimeoutError('simulated'))),{},force=True)
            command=shlex.split(failed['retry_command'])
            self.assertEqual(command[0],sys.executable)
            self.invoke(*command[3:])
            self.assertEqual(store.current()[0]['status'],'review')
