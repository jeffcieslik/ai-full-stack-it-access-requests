"""Bounded scheduling, renewable claims and persisted retry attempts."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import threading
import time

from .config import make_provider


def _work(store, job, token, factory):
    stopped = threading.Event()
    def heartbeat():
        while not stopped.wait(20):
            if not store.renew(job,token):
                return
    thread = threading.Thread(target=heartbeat,daemon=True)
    thread.start()
    try:
        attempt = store.get(job)
        try:
            record = store.execute(job,factory(attempt['settings']))
        except Exception as error:
            record = {'document_id':attempt['document_id'],'source_sha256':attempt['source_sha256'],
                      'extraction':None,'status':'error','owner':'IT Service Desk',
                      'next_action':'retry-extraction','error':'Input or configuration error: '+type(error).__name__,
                      'response_source':('mock' if attempt['settings']['provider']=='mock' else 'openai:'+attempt['settings']['model'])}
        published = store.finish(job,token,record)
        return job,record,published
    finally:
        stopped.set()
        thread.join()


def run_pending(store, *, job_ids=None, workers=4, rate_per_minute=60,
                max_attempts=3, retry_delay=1, provider_factory=None):
    if workers < 1 or max_attempts < 1 or rate_per_minute < 0 or retry_delay < 0:
        raise ValueError('Workers/attempts must be positive; rate and retry delay nonnegative')
    factory = provider_factory or make_provider
    selected = set(job_ids) if job_ids is not None else None
    running = {}
    counts = {}
    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while True:
            pending = [item for item in store.pending() if selected is None or item['id'] in selected]
            for item in pending:
                if len(running) >= workers:
                    break
                if item['id'] in running.values():
                    continue
                token = store.claim(item['id'],max_inflight=workers,rate_per_minute=rate_per_minute)
                if token:
                    future = pool.submit(_work,store,item['id'],token,factory)
                    running[future] = item['id']
            if not pending and not running:
                break
            if not running:
                time.sleep(.05)
                continue
            done,_ = wait(running,timeout=.05,return_when=FIRST_COMPLETED)
            for future in done:
                job,record,finished = future.result()
                del running[future]
                completed += int(finished)
                count = counts.get(job,1)
                if finished and record.get('retryable') and count < max_attempts:
                    # Do not retry an obsolete generation over a newer source.
                    if any(row['attempt_id']==job and 'newer_pending_attempt' not in row for row in store.current()):
                        new = store.retry(job,delay=min(30,retry_delay*2**(count-1)))
                        counts[new] = count+1
                        if selected is not None:
                            selected.add(new)
    return {'completed_attempts':completed,'pending':len(store.pending()),
            'current_documents':len(store.current())}
