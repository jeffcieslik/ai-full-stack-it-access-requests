"""Source-owned expected facts and an explicit fixed-denominator comparison."""
import json
from pathlib import Path

from .core import SCALARS, validate_extraction


def compare(records, expected):
    actual = {}
    for record in records:
        if not isinstance(record,dict) or not isinstance(record.get('document_id'),str):
            raise ValueError('Accuracy input records require a string document_id')
        if record['document_id'] in actual:
            raise ValueError('Duplicate current record in accuracy input')
        actual[record['document_id']] = record
    result = {'matched':0,'total':len(expected)*len(SCALARS),'routing_matches':0,
              'documents':len(expected),'differences':[],'quote_errors':[],
              'issue_errors':[],'schema_errors':[],'routing_differences':[],
              'unexpected_documents':sorted(set(actual)-set(expected))}
    for name,oracle in expected.items():
        record = actual.get(name,{})
        value = record.get('extraction') if record.get('status') != 'error' else None
        if not isinstance(value,dict):
            value = None
        for field in SCALARS:
            if value is not None and field in value and value[field] == oracle['facts'][field]:
                result['matched'] += 1
            else:
                result['differences'].append({'document_id':name,'field':field,
                    'expected':oracle['facts'][field],
                    'actual':value.get(field) if isinstance(value,dict) else '<missing/error extraction>'})
        if all(record.get(field)==value for field,value in oracle['route'].items()):
            result['routing_matches'] += 1
        else:
            result['routing_differences'].append({'document_id':name,'expected':oracle['route'],
                'actual':{field:record.get(field) for field in oracle['route']}})
        if value is None:
            result['schema_errors'].append(name+': no valid extraction')
            continue
        try:
            validate_extraction(value)
        except ValueError:
            result['schema_errors'].append(name+': schema invalid')
        quotes = value.get('supporting_quotes')
        if not isinstance(quotes,list) or not quotes or any(not isinstance(quote,str) or quote not in oracle['source_quote'] for quote in quotes):
            result['quote_errors'].append(name)
        issues = value.get('issues') if isinstance(value.get('issues'),list) else []
        for field,expected_value in oracle['facts'].items():
            if expected_value is None and not any(isinstance(issue,str) and field in issue for issue in issues):
                result['issue_errors'].append(name+': missing explanation for '+field)
        if oracle['route']['next_action']=='inspect-message' and not any(isinstance(issue,str) and issue.lower().startswith('override:') for issue in issues):
            result['issue_errors'].append(name+': missing override issue')
    return result


def report(records, expected, result):
    configurations = []
    for record in records:
        config = {'response_source':record['response_source'],
                  'settings':record.get('processing_settings',{})}
        if config not in configurations:
            configurations.append(config)
    lines = ['# Accuracy and factual comparison','',
        'These expected facts were transcribed from the messages and office policy in planning/plan.md before the extraction implementation or measured outputs. The independent machine-readable oracle is tests/expected.json; it is never regenerated from extractions. Mock fixtures were authored from this same source review for repeatability, so matching mock replay does not measure live model accuracy.','',
        '## Comparison procedure','',
        'For every expected document, compare all twelve scalar fields: '+', '.join(SCALARS)+'. Use exact decoded string equality (including business-purpose wording) and null equality. Do not lowercase, trim, infer dates or award partial credit. The canonical business-purpose excerpts below are measurement choices; another faithful summary may differ in exact-match score without being a factual error.','',
        f'Denominator: {len(expected)} documents × 12 scalar fields = {result["total"]}. A missing/error extraction contributes zero of twelve, even where expected values are null. Absent fields also fail. Historical attempts and repeated runs do not enlarge or shrink the denominator. Duplicate current IDs are rejected; unexpected IDs are reported separately. No minimum score is invented.','',
        'Routing triples (status, owner, next_action), schema validity, decoded quote-substring integrity and required missing/override issue coverage are checked separately from scalar exact matches; quote/issue ordering and prose do not receive scalar credit. Conflicting/corrected facts are judged against the source/policy, not against another model output.','',
        '## Recorded observation','',
        f'Scalar exact matches: **{result["matched"]}/{result["total"]}**. Routing matches: **{result["routing_matches"]}/{result["documents"]}**. Schema errors: {len(result["schema_errors"])}; quote errors: {len(result["quote_errors"])}; issue errors: {len(result["issue_errors"])}. Response sources: '+', '.join(sorted({r['response_source'] for r in records}))+'.',
        '', 'No live-provider observation was made for the committed mock deliverables. A clean mock match is a pipeline/comparison regression result, not a live-model accuracy claim. Tests deliberately change a field (251/252), fail a document (240/252), and omit a document without reducing the 252 denominator.','',
        'Factual-error reporting: inspect every differing document/field below, including expected and actual values; distinguish an incorrect/missing fact from a faithful alternative purpose wording in human review. Absence of differences in mock replay is not evidence that a live model never hallucinates.','',
        '```json',json.dumps(result,ensure_ascii=False,indent=2),'```','',
        '## Model and configuration','', '```json',json.dumps(configurations,ensure_ascii=False,indent=2),'```','',
        '## Source-derived expectations','',
        'Every row quotes its complete source message so that all scalar expectations, including absent facts, can be reviewed independently. Policy: materials/office-policy.md §§ Extracted facts and Review queue; missing/unresolved scalars are null, corrections replace earlier values, unlabelled conflicts remain unresolved and relative dates remain null. IT-006 read permission and IT-014 retained reversed dates follow the user decision recorded in planning/plan.md.','',
        '| Document | Expected scalar facts | Expected routing | Exact source quote |',
        '|---|---|---|---|']
    for name,item in expected.items():
        cells = [name,'`'+json.dumps(item['facts'],ensure_ascii=False,sort_keys=True)+'`',
                 '`'+json.dumps(item['route'],sort_keys=True)+'`','“'+item['source_quote']+'”']
        lines.append('| '+' | '.join(cell.replace('|','\\|').replace('\n','<br>') for cell in cells)+' |')
    lines += ['', 'IT-021.json is the authored paraphrase under tests/inputs/, with fresh wording quoted above. The current queue/extractions submission workspace contains only the supplied 20 messages; accuracy uses a separate 21-document temporary workspace.','']
    return '\n'.join(lines)
