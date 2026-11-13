"""Input identity, strict JSON and extraction validation."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json(text):
    def invalid_number(value):
        raise ValueError(f"Non-JSON number: {value}")
    return json.loads(text, object_pairs_hook=_unique_object, parse_constant=invalid_number)


def resource_path(name):
    """Use source authorities in a checkout; bundled resources in a wheel."""
    relative = 'materials/office-policy.md' if name == 'office-policy.md' else name
    checkout = Path(__file__).resolve().parents[2] / relative
    return checkout if checkout.is_file() else Path(__file__).with_name(name)


SCHEMA = strict_json(resource_path('snapshot.schema.json').read_text())
VALIDATOR = Draft202012Validator(SCHEMA)
SCALARS = tuple(key for key in SCHEMA['required'] if key not in ('supporting_quotes', 'issues'))


@dataclass(frozen=True)
class Source:
    document_id: str
    raw: bytes
    source_sha256: str
    message: str
    metadata: dict


def decode_source(document_id: str, raw: bytes) -> Source:
    export = strict_json(raw.decode('utf-8'))
    if not isinstance(export, dict) or not isinstance(export.get('message'), str):
        raise ValueError('Export must be an object with a message string')
    return Source(document_id, raw, sha256(raw), export['message'],
                  {key:value for key,value in export.items() if key != 'message'})


def load_source(path: str | Path) -> Source:
    path = Path(path)
    return decode_source(path.name, path.read_bytes())


def validate_extraction(value, message: str | None = None) -> None:
    try:
        VALIDATOR.validate(value)
    except ValidationError as error:
        raise ValueError(f'Invalid extraction at {list(error.path)}: {error.message}') from error
    if message is not None:
        for quote in value['supporting_quotes']:
            if not quote or quote not in message:
                raise ValueError('Supporting quote is not an exact decoded-message substring')
