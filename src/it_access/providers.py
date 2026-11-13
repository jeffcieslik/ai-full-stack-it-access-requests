"""Provider boundary and reproducible fixture-backed model replies."""

from collections.abc import Callable
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .core import SCHEMA, strict_json


@dataclass(frozen=True)
class ProviderReply:
    """An unvalidated provider envelope together with its provenance."""

    raw_response: Any
    response_source: str


class Provider(Protocol):
    def complete(
        self, *, message: str, fixture_name: str | None = None
    ) -> ProviderReply:
        """Return a raw reply; extraction validation belongs to the caller."""
        ...


class MockProvider:
    """Read saved replies without consulting credentials or the network.

    A before_response hook can wait on a test-controlled barrier or raise an
    injected exception, so later recovery tests need neither real delays nor
    real provider failures. Invalid fixture envelopes are returned unchanged
    for the application's response validator to inspect.
    """

    def __init__(
        self,
        *,
        fixture_dir: str | Path,
        credential_supplier: Callable[[], str] | None = None,
        before_response: Callable[[str], None] | None = None,
    ) -> None:
        self.fixture_dir = Path(fixture_dir)
        self.calls: list[dict[str, str]] = []
        self._before_response = before_response
        # The common construction boundary accepts a supplier, but mock mode
        # deliberately neither stores it nor calls it.

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def complete(
        self, *, message: str, fixture_name: str | None = None
    ) -> ProviderReply:
        if fixture_name is None:
            raise ValueError("Mock mode requires a saved response fixture name")

        self.calls.append({"message": message, "fixture_name": fixture_name})
        if self._before_response is not None:
            self._before_response(fixture_name)

        raw_response = strict_json(
            (self.fixture_dir / fixture_name).read_text(encoding="utf-8")
        )
        if isinstance(raw_response, dict) and 'mock_error' in raw_response:
            error = raw_response['mock_error']
            raise ProviderError(error['message'], retryable=error.get('retryable', False))
        return ProviderReply(raw_response=raw_response, response_source="mock")


class ProviderError(RuntimeError):
    def __init__(self, message, *, retryable=False, code='provider_error'):
        super().__init__(message)
        self.retryable = retryable
        self.code = code


def build_request(message, model, max_completion_tokens=4096, *, prompt=None, schema=None):
    return {'model':model, 'messages':[
        {'role':'system','content':prompt if prompt is not None else Path(__file__).with_name('prompt.txt').read_text()},
        {'role':'user','content':message}],
        'max_completion_tokens':max_completion_tokens,
        'response_format':{'type':'json_schema','json_schema':{
            'name':'access_request','strict':True,'schema':schema if schema is not None else SCHEMA}}}


def http_transport(url, payload, headers, timeout):
    request = Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
    try:
        with urlopen(request, timeout=timeout) as response:
            return strict_json(response.read().decode('utf-8'))
    except HTTPError as error:
        # Never retain/print provider error bodies or request Authorization.
        raise ProviderError(f'Provider HTTP {error.code}',
                            retryable=error.code in (408, 429) or error.code >= 500,
                            code=f'http_{error.code}') from None
    except (URLError, TimeoutError, OSError):
        raise ProviderError('Provider connection failed or timed out', retryable=True,code='connection_or_timeout') from None


class OpenAIProvider:
    def __init__(self, *, model, base_url='https://api.openai.com/v1', timeout=60,
                 max_completion_tokens=4096, credential_supplier=None, transport=None, prompt=None, schema=None):
        if not model:
            raise ValueError('A model ID is required for provider mode')
        self.model = model
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.max_completion_tokens = max_completion_tokens
        self.credential_supplier = credential_supplier or (lambda: os.environ['API_KEY'])
        self.transport = transport or http_transport
        self.response_source = 'openai:' + model
        self.prompt = prompt
        self.schema = schema

    def complete(self, *, message, fixture_name=None):
        try:
            credential = self.credential_supplier()
        except (KeyError, ValueError):
            raise ProviderError('Provider mode requires API_KEY in the environment',code='missing_api_key') from None
        if not credential:
            raise ProviderError('Provider mode requires a nonempty API_KEY',code='missing_api_key')
        try:
            raw = self.transport(self.base_url + '/chat/completions',
                                 build_request(message,self.model,self.max_completion_tokens,prompt=self.prompt,schema=self.schema),
                                 {'Authorization':'Bearer '+credential,'Content-Type':'application/json'},
                                 self.timeout)
        except ProviderError:
            raise
        except Exception as error:
            raise ProviderError('Provider transport/response failed: '+type(error).__name__) from None
        returned_model = raw.get('model') if isinstance(raw,dict) else None
        return ProviderReply(raw, 'openai:'+returned_model if isinstance(returned_model,str) else self.response_source)
