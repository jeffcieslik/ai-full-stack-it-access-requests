"""Independent expectations and guards shared by offline acceptance tests."""
import json
import os
from pathlib import Path
import socket
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/mock_responses"
EXPECTED = json.loads((ROOT / "tests/expected.json").read_text())


def envelope(name="it-001.json"):
    return json.loads((FIXTURES / name).read_text())


def extraction(name="it-001.json"):
    return json.loads(envelope(name)["choices"][0]["message"]["content"])


class NoCredentials(dict):
    def __getitem__(self, key):
        if key == "API_KEY":
            raise AssertionError("A test attempted to read API_KEY")
        return super().__getitem__(key)

    def get(self, key, default=None):
        if key == "API_KEY":
            raise AssertionError("A test attempted to read API_KEY")
        return super().get(key, default)


class OfflineTest(unittest.TestCase):
    def setUp(self):
        for patcher in (
            mock.patch.object(os, "environ", NoCredentials()),
            mock.patch.object(socket, "create_connection", side_effect=AssertionError("network forbidden")),
            mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")),
            mock.patch.object(socket.socket, "connect_ex", side_effect=AssertionError("network forbidden")),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
