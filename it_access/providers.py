"""Provider boundary and reproducible fixture-backed model replies."""

from collections.abc import Callable
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Protocol


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

        raw_response = json.loads(
            (self.fixture_dir / fixture_name).read_text(encoding="utf-8")
        )
        return ProviderReply(raw_response=raw_response, response_source="mock")
