"""S01 / T01: the fixture-backed provider contract, before implementation.

Expected behavior: planning/plan.md, T01 and E-001 (R-103).
The saved envelope is authored from IT-001 and the office policy, not app output.
Run from the repository root with API_KEY unset:
    env -u API_KEY python3 -m unittest discover -s tests -p test_provider.py -v
"""

import json
import os
from pathlib import Path
import socket
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "mock_responses"


class CredentialReadsForbidden(dict):
    """An empty replacement environment that rejects credential lookups."""

    def __getitem__(self, key):
        if key == "API_KEY":
            raise AssertionError("Mock mode must not read API_KEY")
        return super().__getitem__(key)

    def get(self, key, default=None):
        if key == "API_KEY":
            raise AssertionError("Mock mode must not read API_KEY")
        return super().get(key, default)

    def __contains__(self, key):
        if key == "API_KEY":
            raise AssertionError("Mock mode must not inspect API_KEY")
        return super().__contains__(key)


class MockProviderTests(unittest.TestCase):
    def test_mock_provider_contract(self):
        source = json.loads(
            (ROOT / "materials" / "requests" / "IT-001.json").read_text(
                encoding="utf-8"
            )
        )
        message = source["message"]
        expected_envelope = json.loads(
            (FIXTURES / "it-001.json").read_text(encoding="utf-8")
        )
        credentials = mock.Mock(
            side_effect=AssertionError("Mock mode must not request credentials")
        )
        network = mock.Mock(
            side_effect=AssertionError("A test attempted a network connection")
        )

        # Replace the environment object without copying or reading its values.
        # Guard the implementation's import as well as construction and calls.
        with (
            mock.patch.object(os, "environ", CredentialReadsForbidden()),
            mock.patch.object(socket, "create_connection", network),
            mock.patch.object(socket.socket, "connect", network),
            mock.patch.object(socket.socket, "connect_ex", network),
        ):
            from it_access.providers import MockProvider

            provider = MockProvider(
                fixture_dir=FIXTURES,
                credential_supplier=credentials,
            )
            result = provider.complete(
                message=message,
                fixture_name="it-001.json",
            )

            # S01 returns the unprocessed envelope; extraction/routing is S03.
            self.assertEqual(result.raw_response, expected_envelope)
            self.assertEqual(result.response_source, "mock")
            self.assertEqual(provider.call_count, 1)
            self.assertEqual(
                provider.calls,
                [{"message": message, "fixture_name": "it-001.json"}],
            )

        credentials.assert_not_called()
        network.assert_not_called()


if __name__ == "__main__":
    unittest.main()
