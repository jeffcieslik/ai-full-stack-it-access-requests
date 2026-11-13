"""Nonsecret, reproducible processing configuration snapshots."""
import json
from pathlib import Path
from urllib.parse import urlsplit

from .core import resource_path, sha256, strict_json

EXTRACTION_VERSION = '1'
ROUTING_VERSION = '1'


def settings(value=None):
    value = value or {}
    selected = {
        'provider':value.get('provider','mock'),
        'model':value.get('model','mock'),
        'base_url':value.get('base_url','https://api.openai.com/v1'),
        'fixture_dir':str(Path(value.get('fixture_dir','tests/mock_responses')).resolve()),
        'timeout':value.get('timeout',60),
        'max_completion_tokens':value.get('max_completion_tokens',4096),
        'prompt':value.get('prompt',Path(__file__).with_name('prompt.txt').read_text()),
        'schema':value.get('schema',strict_json(resource_path('snapshot.schema.json').read_text())),
        'extraction_version':value.get('extraction_version',EXTRACTION_VERSION),
    }
    parsed = urlsplit(selected['base_url'])
    if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Provider base URL must be credential-free HTTPS without query or fragment')
    selected['extraction_fingerprint'] = sha256(json.dumps(selected,sort_keys=True).encode())
    policy = value.get('policy_text',resource_path('office-policy.md').read_text())
    selected['policy_text'] = policy
    selected['policy_version'] = value.get('policy_version',sha256((policy+'\nrouter:'+ROUTING_VERSION).encode()))
    return selected


def make_provider(config):
    from .providers import MockProvider, OpenAIProvider
    if config['provider'] == 'mock':
        return MockProvider(fixture_dir=config['fixture_dir'])
    if config['provider'] != 'openai':
        raise ValueError('Supported providers: mock, openai')
    return OpenAIProvider(model=config['model'],base_url=config['base_url'],
                          timeout=config['timeout'],max_completion_tokens=config['max_completion_tokens'],
                          prompt=config['prompt'],schema=config['schema'])
