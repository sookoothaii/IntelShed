import os
import unittest
from unittest import mock

import ollama_config as oc


class TestOllamaConfig(unittest.TestCase):
    def test_keep_alive_default(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(oc.keep_alive(), "1m")

    def test_keep_alive_env(self):
        with mock.patch.dict(os.environ, {"OLLAMA_KEEP_ALIVE": "0"}, clear=True):
            self.assertEqual(oc.keep_alive(), "0")

    def test_background_keep_alive_default(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(oc.background_keep_alive(), "0")

    def test_background_keep_alive_env(self):
        with mock.patch.dict(os.environ, {"OLLAMA_BACKGROUND_KEEP_ALIVE": "30s"}, clear=True):
            self.assertEqual(oc.background_keep_alive(), "30s")


if __name__ == "__main__":
    unittest.main()
