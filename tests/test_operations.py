from concurrent.futures import ThreadPoolExecutor
import multiprocessing
from pathlib import Path
import tempfile
import threading
import time

from support import FIXTURES, ROOT, OfflineTest


def claim_in_process(path, job, output, crash=False):
    from it_access.state import Store
    store=Store(path)
    token=store.claim(job,lease_seconds=.1 if crash else 120)
    if crash:
        import os
        os._exit(7)
    output.put(token)


class OperationTests(OfflineTest):
    def resources(self,directory):
        from it_access.core import load_source
        from it_access.state import Store
        return Store(Path(directory)/'state.db'),load_source(ROOT/'materials/requests/IT-001.json')

    def test_overlapping_operators_and_fencing(self):
        from it_access.worker import run_pending
        from it_access.core import decode_source
        from it_access.providers import MockProvider
        from it_access.pipeline import process
        with tempfile.TemporaryDirectory() as directory:
            store,source=self.resources(directory)
            job=store.register(source,{})
            context=multiprocessing.get_context('fork'); output=context.Queue()
            processes=[context.Process(target=claim_in_process,args=(store.path,job,output)) for _ in range(2)]
            for child in processes: child.start()
            for child in processes: child.join(10); self.assertEqual(child.exitcode,0)
            tokens=[output.get(timeout=2) for _ in processes]
            self.assertEqual(sum(token is not None for token in tokens),1)
            newer=decode_source(source.document_id,source.raw+b'\n')
            latest=store.register(newer,{})
            token=next(token for token in tokens if token)
            store.finish(job,token,process(source,MockProvider(fixture_dir=FIXTURES)))
            self.assertEqual(store.current(),[])
            run_pending(store,workers=2,rate_per_minute=0)
            self.assertEqual(store.current()[0]['attempt_id'],latest)
            self.assertEqual(store.current()[0]['source_sha256'],newer.source_sha256)

    def test_interruption_recovery(self):
        from it_access.worker import run_pending
        from it_access.state import Store
        from it_access.providers import MockProvider
        with tempfile.TemporaryDirectory() as directory:
            store,source=self.resources(directory)
            completed=store.run(source,MockProvider(fixture_dir=FIXTURES),{})
            job=store.register(source,{},force=True)
            context=multiprocessing.get_context('fork')
            child=context.Process(target=claim_in_process,args=(store.path,job,None,True))
            child.start();child.join(10);self.assertEqual(child.exitcode,7)
            recovered=Store(store.path,clock=lambda:time.time()+1)
            self.assertEqual(len(recovered.pending()),1)
            run_pending(recovered,rate_per_minute=0)
            self.assertEqual(len(recovered.pending()),0)
            self.assertEqual(len(recovered.history(source.document_id)),2)
            self.assertEqual(recovered.current()[0]['extraction'],completed['extraction'])

    def test_slow_rate_limited_and_unavailable(self):
        from it_access.worker import run_pending
        from it_access.core import load_source
        from it_access.providers import MockProvider,ProviderError
        with tempfile.TemporaryDirectory() as directory:
            store,source=self.resources(directory)
            store.register(source,{})
            store.register(load_source(ROOT/'materials/requests/IT-008.json'),{})
            blocked=threading.Event();release=threading.Event()
            def before(name):
                if name=='it-001.json':
                    blocked.set()
                    if not release.wait(5):raise TimeoutError('test barrier timed out')
            provider=MockProvider(fixture_dir=FIXTURES,before_response=before)
            with ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(run_pending,store,workers=2,rate_per_minute=0,provider_factory=lambda config:provider)
                self.assertTrue(blocked.wait(5))
                deadline=time.monotonic()+5
                while not store.current() and time.monotonic()<deadline:time.sleep(.01)
                self.assertEqual(store.current()[0]['document_id'],'IT-008.json')
                release.set();future.result(timeout=10)
            job=store.register(source,{},force=True)
            failures=[]
            def transient(name):
                if len(failures)<2:
                    failures.append(name);raise ProviderError('Simulated HTTP 429/503',retryable=True)
            provider=MockProvider(fixture_dir=FIXTURES,before_response=transient)
            run_pending(store,job_ids=[job],rate_per_minute=0,retry_delay=0,provider_factory=lambda config:provider)
            self.assertEqual(store.current()[0]['status'],'review')
            self.assertEqual(len(failures),2)

    def test_peak_mock_workload(self):
        from it_access.worker import run_pending
        from it_access.core import decode_source
        from it_access.providers import MockProvider
        with tempfile.TemporaryDirectory() as directory:
            store,source=self.resources(directory)
            for number in range(2000):
                store.register(decode_source(f'LOAD-{number:04}.json',source.raw),{})
            provider=MockProvider(fixture_dir=FIXTURES)
            original=provider.complete
            provider.complete=lambda **kwargs:original(message=kwargs['message'],fixture_name='it-001.json')
            run_pending(store,workers=4,rate_per_minute=0,provider_factory=lambda config:provider)
            self.assertEqual(len(store.current()),2000)
            self.assertEqual(len(store.pending()),0)
            self.assertEqual(provider.call_count,2000)

    def test_shared_request_budget(self):
        from it_access.state import Store
        from it_access.core import load_source
        with tempfile.TemporaryDirectory() as directory:
            first,source=self.resources(directory)
            first.clock=lambda:100
            second=Store(first.path,clock=lambda:100)
            one=first.register(source,{})
            two=first.register(load_source(ROOT/'materials/requests/IT-008.json'),{})
            self.assertIsNotNone(first.claim(one,max_inflight=2,rate_per_minute=1))
            self.assertIsNone(second.claim(two,max_inflight=2,rate_per_minute=1))
            second.clock=lambda:161
            self.assertIsNotNone(second.claim(two,max_inflight=2,rate_per_minute=1))

    def test_retry_budget(self):
        from it_access.worker import run_pending
        from it_access.providers import MockProvider,ProviderError
        with tempfile.TemporaryDirectory() as directory:
            store,source=self.resources(directory)
            store.register(source,{})
            provider=MockProvider(fixture_dir=FIXTURES,before_response=lambda name:(_ for _ in ()).throw(ProviderError('simulated 503',retryable=True)))
            run_pending(store,rate_per_minute=0,retry_delay=0,max_attempts=3,provider_factory=lambda config:provider)
            self.assertEqual(provider.call_count,3)
            self.assertEqual(len(store.history(source.document_id)),3)
            self.assertEqual(store.current()[0]['status'],'error')
