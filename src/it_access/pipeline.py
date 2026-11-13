"""Validated extraction and ordered human-review routing."""
from datetime import date
from pathlib import Path
import re

from .core import SCALARS, strict_json, validate_extraction

REQUIRED = tuple(key for key in SCALARS if key != 'kind')


def route(value):
    issues = value['issues']
    if any(issue.lower().startswith('override:') for issue in issues):
        return 'review', 'IT Service Desk', 'inspect-message'
    if value['kind'] == 'withdrawal' and value['request_id'] and value['request_date']:
        return 'review', 'IT Service Desk', 'confirm-withdrawal'
    if (value['kind'] not in ('new', 'change')
            or any(value[key] is None for key in REQUIRED)
            or any(issue.lower().startswith(('conflict:', 'mismatch:', 'date-order:')) for issue in issues)
            or (value['start_date'] and value['end_date'] and value['start_date'] > value['end_date'])):
        return 'needs-information', 'IT Service Desk', 'clarify'
    if value['environment'] == 'production' or value['permission'] in ('write', 'admin'):
        return 'review', 'Security Review', 'review-risk-then-owner'
    return 'review', 'System Owner', 'review-request'


def decode_reply(reply, source):
    raw = reply.raw_response
    if not isinstance(raw, dict) or not isinstance(raw.get('choices'), list) or len(raw['choices']) != 1:
        raise ValueError('Provider response must contain exactly one choice')
    choice = raw['choices'][0]
    message = choice.get('message', {})
    if message.get('refusal'):
        raise ValueError('Provider refused extraction')
    if choice.get('finish_reason') != 'stop':
        raise ValueError('Provider response is interrupted or has unsupported completion status')
    content = message.get('content')
    if not isinstance(content, str):
        raise ValueError('Provider returned no text extraction')
    value = strict_json(content)
    validate_extraction(value, source.message)
    for field in SCALARS:
        item = value[field]
        if isinstance(item, str) and not item.strip():
            raise ValueError(f'Empty {field}: use null and an explanatory issue')
        if item is None and not any(field in issue for issue in value['issues']):
            value['issues'].append(f'missing:{field}: absent or unresolved in message')
    for field in ('request_date', 'start_date', 'end_date'):
        item = value[field]
        if item is not None:
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', item):
                raise ValueError(f'{field} must use YYYY-MM-DD')
            date.fromisoformat(item)
    if value['request_id'] and value['request_id'] != Path(source.document_id).stem:
        issue = f'mismatch:request_id: {value["request_id"]} differs from {source.document_id}'
        if issue not in value['issues']:
            value['issues'].append(issue)
    if value['start_date'] and value['end_date'] and value['start_date'] > value['end_date']:
        if not any(issue.startswith('date-order:') for issue in value['issues']):
            value['issues'].append('date-order:start_date after end_date')
    marker = re.search(r'SYSTEM\s+OVERRIDE\s*:', source.message, re.IGNORECASE)
    if marker:
        evidence = source.message[marker.start():]
        if not any(issue.lower().startswith('override:') for issue in value['issues']):
            value['issues'].append('override:' + evidence)
        if evidence not in value['supporting_quotes']:
            value['supporting_quotes'].append(evidence)
    return value


def extract(source, provider):
    reply = provider.complete(message=source.message, fixture_name=source.document_id.lower())
    value = decode_reply(reply, source)
    status, owner, action = route(value)
    return {'document_id':source.document_id, 'source_sha256':source.source_sha256,
            'extraction':value, 'status':status, 'owner':owner, 'next_action':action,
            'error':None, 'response_source':reply.response_source, 'export_metadata':source.metadata}


def process(source, provider):
    """Isolate a failed message without substituting an older extraction."""
    try:
        return extract(source, provider)
    except Exception as error:
        # Details from a live reply may contain an echoed secret. Preserve only
        # a safe category there; mock diagnostics are local exercise data.
        provenance = getattr(provider, 'response_source', 'mock')
        detail = (str(error) if provenance == 'mock' else
                  'Extraction failed: '+str(getattr(error,'code',type(error).__name__)))
        return {'document_id':source.document_id,'source_sha256':source.source_sha256,
                'extraction':None,'status':'error','owner':'IT Service Desk',
                'next_action':'retry-extraction','error':detail,
                'response_source':provenance,'export_metadata':source.metadata,
                'retryable':bool(getattr(error,'retryable',False))}
