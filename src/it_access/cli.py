"""Operator commands; all intake defaults to reproducible mock responses."""
import argparse
import json
from pathlib import Path
import sys
import tempfile

from .config import settings
from .core import Source, decode_source, sha256
from .state import Store
from .worker import run_pending


def parser():
    result = argparse.ArgumentParser(description='Prepare an access-request queue for human review')
    commands = result.add_subparsers(dest='command',required=True)
    for name in ('intake','queue','pending','history','retry','resume','export','verify-exports','accuracy','request-evidence'):
        command = commands.add_parser(name)
        command.add_argument('--state',default='.state/intake.db')
        if name in ('intake','retry','resume','accuracy'):
            command.add_argument('--workers',type=int,default=4)
            command.add_argument('--rate-per-minute',type=int,default=None)
            command.add_argument('--max-attempts',type=int,default=3)
        if name in ('intake','accuracy'):
            command.add_argument('--input',action='append',required=True)
            command.add_argument('--provider',choices=['mock','openai'],default='mock')
            command.add_argument('--model')
            command.add_argument('--base-url',default='https://api.openai.com/v1')
            command.add_argument('--fixtures',default='tests/mock_responses')
            command.add_argument('--timeout',type=float,default=60)
            command.add_argument('--max-completion-tokens',type=int,default=4096)
            command.add_argument('--force',action='store_true')
            command.add_argument('--enqueue-only',action='store_true')
        if name == 'accuracy':
            command.add_argument('--expected',default='tests/expected.json')
            command.add_argument('--records',help='Compare existing JSONL instead of running intake')
            command.add_argument('--output',default='deliverables/accuracy.md')
        if name == 'request-evidence':
            command.add_argument('--input',default='materials/requests/IT-001.json')
            command.add_argument('--model',default='gpt-5.4-mini-2026-03-17')
            command.add_argument('--output',default='deliverables/request-evidence.json')
        if name == 'history':
            command.add_argument('--document',required=True)
        if name == 'retry':
            command.add_argument('--attempt',type=int,required=True)
        if name in ('export','verify-exports'):
            command.add_argument('--output',default='deliverables')
    return result


def discover(inputs):
    sources = {}
    for name in inputs:
        path = Path(name)
        paths = sorted(path.glob('*.json')) if path.is_dir() else [path]
        if not paths:
            raise ValueError('Input directory contains no JSON exports')
        for item in paths:
            raw = item.read_bytes()
            if item.name in sources:
                raise ValueError('Duplicate input filename in this batch: '+item.name)
            try:
                source = decode_source(item.name,raw)
            except (UnicodeError, ValueError):
                # Retain malformed input bytes as a failed document, rather than
                # stopping unaffected documents. The worker exposes its error.
                source = Source(item.name,raw,sha256(raw),'',{})
            sources[item.name] = source
    return list(sources.values())


def dispatch(args):
    if args.command == 'request-evidence':
        from .providers import build_request
        from .core import load_source
        source = load_source(args.input)
        example = {'observation':'Illustrative request built by production serializer; not sent to a provider',
                   'provider':'openai','method':'POST','url':'https://api.openai.com/v1/chat/completions',
                   'headers':{'Authorization':'Bearer <redacted>','Content-Type':'application/json'},
                   'body':build_request(source.message,args.model),
                   'timeout_seconds':60,
                   'committed_outputs':'mock responses only; model=mock; no live observation',
                   'response_handling':{
                       'success':'Exactly one choice, finish_reason=stop, no refusal, text JSON matching snapshot.schema.json and decoded source quotes',
                       'refusal':'Explicit extraction error; never treated as an extraction',
                       'interrupted':'length, content_filter, tool_calls, missing/unknown completion status and truncated output rejected',
                       'malformed':'Strict JSON, duplicate keys, types, enums, required/extra properties and invented quotes checked',
                       'provider_errors':'HTTP 408/429/5xx and connection/timeouts retryable; other HTTP errors terminal; bodies and Authorization omitted from diagnostics',
                       'recovery':'Latest failed attempt is error/null with retry command; earlier success stays in history',
                       'implementation':['src/it_access/providers.py','src/it_access/pipeline.py','src/it_access/worker.py']}}
        output = Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(example,ensure_ascii=False,indent=2)+'\n')
        return {'written':str(output),'provider_call_made':False}
    if args.command == 'accuracy':
        from .accuracy import compare, report
        from .core import strict_json
        expected = strict_json(Path(args.expected).read_text())
        if args.records:
            records = [strict_json(line) for line in Path(args.records).read_text().splitlines()]
        else:
            with tempfile.TemporaryDirectory(prefix='it-access-accuracy-') as temporary:
                from argparse import Namespace
                invocation = Namespace(**vars(args))
                invocation.command='intake'; invocation.state=str(Path(temporary)/'state.db')
                invocation.enqueue_only=False;invocation.force=False
                dispatch(invocation)
                records = Store(invocation.state).current()
        result = compare(records,expected)
        output = Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(report(records,expected,result))
        return result
    if args.command == 'verify-exports':
        from .exporting import read_exports
        records,queue = read_exports(args.output)
        return {'verified_documents':len(records),'queue_entries':len(queue)}
    store = Store(args.state)
    if args.command == 'export':
        from .exporting import export_current
        return export_current(store,args.output)
    if args.command == 'queue':
        return store.current()
    if args.command == 'pending':
        return store.pending()
    if args.command == 'history':
        return [{key:value for key,value in row.items() if key != 'raw'} for row in store.history(args.document)]
    selected = None
    if args.command == 'intake':
        if args.provider == 'openai' and not args.model:
            raise ValueError('Provider mode requires an explicit --model')
        if args.timeout <= 0 or args.max_completion_tokens <= 0:
            raise ValueError('Timeout and completion-token budget must be positive')
        config = settings({'provider':args.provider,'model':args.model or 'mock',
                           'base_url':args.base_url,'fixture_dir':args.fixtures,
                           'timeout':args.timeout,'max_completion_tokens':args.max_completion_tokens})
        sources = discover(args.input)
        selected = [store.register(source,config,force=args.force) for source in sources]
        if args.enqueue_only:
            return {'registered_documents':len(selected),'pending':len(store.pending())}
    elif args.command == 'retry':
        selected = [store.retry(args.attempt)]
    rate = args.rate_per_minute
    if rate is None:
        # A resumed database may include live jobs: default conservatively.
        rate = 0 if args.command == 'intake' and args.provider == 'mock' else 60
    return run_pending(store,job_ids=selected,workers=args.workers,
                       rate_per_minute=rate,max_attempts=args.max_attempts)


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        output = dispatch(args)
    except (OSError, ValueError) as error:
        # Never print a traceback with provider request state/credentials.
        print(json.dumps({'error':str(error)}),file=sys.stderr)
        return 2
    print(json.dumps(output,ensure_ascii=False,indent=2))
    return 0
