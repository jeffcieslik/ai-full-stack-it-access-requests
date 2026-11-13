"""Transactional source snapshots, attempts, current results and recovery."""
from contextlib import contextmanager
import json
from pathlib import Path
import shlex
import sqlite3
import sys
import time
import uuid

from .core import decode_source, sha256
from .pipeline import process
from .config import settings as processing_settings


class Store:
    def __init__(self, path, *, clock=time.time):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY, generation INTEGER NOT NULL,
                    latest_job INTEGER, current_job INTEGER);
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY, document_id TEXT NOT NULL,
                    generation INTEGER NOT NULL, source_sha256 TEXT NOT NULL,
                    raw BLOB NOT NULL, settings TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending', record TEXT,
                    token TEXT, lease REAL, created REAL NOT NULL,
                    finished REAL, parent INTEGER, next_at REAL NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS jobs_state ON jobs(state,next_at);
                CREATE INDEX IF NOT EXISTS jobs_document ON jobs(document_id,id);
                CREATE TABLE IF NOT EXISTS request_starts (started REAL NOT NULL);
            ''')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def register(self, source, settings, *, force=False):
        settings = processing_settings(settings)
        serialized = json.dumps(settings, sort_keys=True)
        fingerprint = sha256(serialized.encode())
        with self.transaction() as db:
            doc = db.execute('SELECT * FROM documents WHERE document_id=?', (source.document_id,)).fetchone()
            latest = db.execute('SELECT * FROM jobs WHERE id=?',(doc['latest_job'],)).fetchone() if doc else None
            if latest and not force and latest['source_sha256'] == source.source_sha256 and latest['fingerprint'] == fingerprint:
                return latest['id']
            generation = doc['generation']+1 if doc else 1
            job = db.execute('''INSERT INTO jobs(document_id,generation,source_sha256,raw,settings,fingerprint,created)
                                VALUES(?,?,?,?,?,?,?)''',
                             (source.document_id,generation,source.source_sha256,source.raw,serialized,fingerprint,self.clock())).lastrowid
            if doc:
                db.execute('UPDATE documents SET generation=?, latest_job=? WHERE document_id=?',
                           (generation,job,source.document_id))
            else:
                db.execute('INSERT INTO documents VALUES(?,?,?,NULL)',(source.document_id,generation,job))
            return job

    def get(self, job):
        with self.connection() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?',(job,)).fetchone()
        if row is None:
            raise ValueError(f'Unknown attempt {job}')
        result = dict(row)
        result['settings'] = json.loads(result['settings'])
        result['record'] = json.loads(result['record']) if result['record'] else None
        return result

    def claim(self, job, *, lease_seconds=120, max_inflight=None, rate_per_minute=0):
        now = self.clock()
        token = uuid.uuid4().hex
        with self.transaction() as db:
            if max_inflight is not None:
                active = db.execute("SELECT count(*) FROM jobs WHERE state='running' AND lease>=?",(now,)).fetchone()[0]
                if active >= max_inflight:
                    return None
            if rate_per_minute:
                db.execute('DELETE FROM request_starts WHERE started<=?',(now-60,))
                if db.execute('SELECT count(*) FROM request_starts').fetchone()[0] >= rate_per_minute:
                    return None
            changed = db.execute('''UPDATE jobs SET state='running',token=?,lease=?
                WHERE id=? AND next_at<=? AND (state='pending' OR (state='running' AND lease<?))''',
                (token,now+lease_seconds,job,now,now)).rowcount
            if changed and rate_per_minute:
                db.execute('INSERT INTO request_starts VALUES(?)',(now,))
        return token if changed else None

    def renew(self, job, token, *, lease_seconds=120):
        with self.transaction() as db:
            return bool(db.execute("UPDATE jobs SET lease=? WHERE id=? AND token=? AND state='running'",
                                   (self.clock()+lease_seconds,job,token)).rowcount)

    def finish(self, job, token, record):
        attempt = self.get(job)
        record = dict(record, attempt_id=job, generation=attempt['generation'],
                      processing_settings=attempt['settings'])
        if record['status'] == 'error':
            record['retry_command'] = (f'{shlex.quote(sys.executable)} -m it_access retry --state {shlex.quote(str(self.path))}'
                                       f' --attempt {job}')
        with self.transaction() as db:
            changed = db.execute("UPDATE jobs SET state='complete',record=?,finished=?,lease=NULL WHERE id=? AND token=? AND state='running'",
                                 (json.dumps(record),self.clock(),job,token)).rowcount
            if changed:
                db.execute('UPDATE documents SET current_job=? WHERE document_id=? AND latest_job=?',
                           (job,attempt['document_id'],job))
        return bool(changed)

    def execute(self, job, provider, *, route_handler=None):
        from .pipeline import route
        attempt = self.get(job)
        source = self.source(job)
        for prior in reversed(self.history(source.document_id)):
            if (prior['id'] < job and prior['record'] and prior['record']['status'] != 'error'
                    and prior['source_sha256'] == source.source_sha256
                    and prior['settings']['extraction_fingerprint'] == attempt['settings']['extraction_fingerprint']
                    and prior['settings']['policy_version'] != attempt['settings']['policy_version']):
                result = dict(prior['record'])
                result['extraction'] = json.loads(json.dumps(result['extraction']))
                result['status'],result['owner'],result['next_action'] = (route_handler or route)(result['extraction'])
                result['extraction_attempt_id'] = prior['record'].get('extraction_attempt_id',prior['id'])
                return result
        return process(source,provider)

    def run(self, source, provider, settings, *, force=False, route_handler=None):
        job = self.register(source,settings,force=force)
        token = self.claim(job)
        if token:
            self.finish(job,token,self.execute(job,provider,route_handler=route_handler))
        return self.get(job)['record']

    def current(self):
        with self.connection() as db:
            db.execute('BEGIN')
            rows = db.execute('''SELECT j.record,d.latest_job,j.id FROM documents d JOIN jobs j ON j.id=d.current_job
                                 ORDER BY d.document_id''').fetchall()
            result = []
            for row in rows:
                record = json.loads(row['record'])
                if row['id'] != row['latest_job']:
                    record['newer_pending_attempt'] = row['latest_job']
                    record['source_notice'] = 'Earlier terminal result; newer work is pending'
                result.append(record)
            return result

    def pending(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute('''SELECT id,document_id,generation,source_sha256,state,lease,next_at
                FROM jobs WHERE state!='complete' ORDER BY id''')]

    def history(self, document_id):
        with self.connection() as db:
            ids = [row[0] for row in db.execute('SELECT id FROM jobs WHERE document_id=? ORDER BY id',(document_id,))]
        return [self.get(job) for job in ids]

    def retry(self, job, *, delay=0):
        old = self.get(job)
        with self.transaction() as db:
            doc = db.execute('SELECT * FROM documents WHERE document_id=?',(old['document_id'],)).fetchone()
            latest = db.execute('SELECT * FROM jobs WHERE id=?',(doc['latest_job'],)).fetchone()
            publish = (latest['source_sha256'] == old['source_sha256'] and latest['fingerprint'] == old['fingerprint'])
            generation = doc['generation']+1 if publish else old['generation']
            new = db.execute('''INSERT INTO jobs(document_id,generation,source_sha256,raw,settings,fingerprint,created,parent,next_at)
                VALUES(?,?,?,?,?,?,?,?,?)''',(old['document_id'],generation,old['source_sha256'],old['raw'],
                 json.dumps(old['settings'],sort_keys=True),old['fingerprint'],self.clock(),job,self.clock()+delay)).lastrowid
            if publish:
                db.execute('UPDATE documents SET generation=?,latest_job=? WHERE document_id=?',(generation,new,old['document_id']))
            return new

    def source(self, job):
        value = self.get(job)
        return decode_source(value['document_id'],value['raw'])
