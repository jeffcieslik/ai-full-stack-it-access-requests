"""Publish and verify a linked pair of current extraction/queue snapshots."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import tempfile
import uuid

from .core import sha256, strict_json


@contextmanager
def export_lock(directory, exclusive):
    directory.mkdir(parents=True,exist_ok=True)
    with (directory/'.export.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(lock,fcntl.LOCK_UN)


def _write(path, content):
    with path.open('wb') as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())


def _sync_directory(path):
    descriptor = os.open(path,os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def export_current(store, directory):
    directory = Path(directory)
    with export_lock(directory,True):
        records = store.current()  # One transactional read snapshot.
        queue = [{key:record.get(key) for key in (
            'document_id','source_sha256','attempt_id','generation','status','owner',
            'next_action','error','response_source','retry_command','newer_pending_attempt','source_notice')}
            | {'policy_version':record['processing_settings']['policy_version'],
               'extraction_fingerprint':record['processing_settings']['extraction_fingerprint']}
            for record in records]
        payloads = {
            'extractions.jsonl':(''.join(json.dumps(item,ensure_ascii=False,sort_keys=True)+'\n' for item in records)).encode(),
            'queue.json':(json.dumps(queue,ensure_ascii=False,indent=2)+'\n').encode()}
        manifest = {'generation':uuid.uuid4().hex,'documents':len(records),
                    'sha256':{name:sha256(raw) for name,raw in payloads.items()}}
        with tempfile.TemporaryDirectory(prefix='.export-',dir=directory) as temporary:
            staging = Path(temporary)
            for name,raw in payloads.items():
                _write(staging/name,raw)
            _write(staging/'snapshot.json',(json.dumps(manifest,indent=2)+'\n').encode())
            _write(directory/'.incomplete',manifest['generation'].encode())
            _sync_directory(directory)
            for name in (*payloads,'snapshot.json'):
                os.replace(staging/name,directory/name)
            _sync_directory(directory)
            (directory/'.incomplete').unlink()
            _sync_directory(directory)
        return manifest


def read_exports(directory):
    directory = Path(directory)
    with export_lock(directory,False):
        if (directory/'.incomplete').exists():
            raise ValueError('Interrupted export: rebuild before accepting this snapshot')
        manifest = strict_json((directory/'snapshot.json').read_text())
        payloads = {name:(directory/name).read_bytes() for name in ('extractions.jsonl','queue.json')}
        for name,raw in payloads.items():
            if sha256(raw) != manifest['sha256'][name]:
                raise ValueError('Export hash mismatch: '+name)
        records = [strict_json(line) for line in payloads['extractions.jsonl'].decode().splitlines()]
        queue = strict_json(payloads['queue.json'].decode())
        identities = [(item['document_id'],item['source_sha256'],item['attempt_id']) for item in records]
        if (len(identities) != len(set(item[0] for item in identities))
                or identities != [(item['document_id'],item['source_sha256'],item['attempt_id']) for item in queue]
                or len(records) != manifest['documents']):
            raise ValueError('Queue/extraction identity or document count mismatch')
        return records,queue
