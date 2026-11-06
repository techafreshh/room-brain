"""LLM client tests: missing-key fast fail, stub JSON, error translation."""

import os
import sys
import time
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_openai_double(captured, content=None, error=None):
    """Build a fake `openai` module whose OpenAI client records kwargs."""
    module = types.ModuleType("openai")

    class _Message:
        def __init__(self, text):
            self.content = text

    class _Choice:
        def __init__(self, text):
            self.message = _Message(text)

    class _Completion:
        def __init__(self, text):
            self.choices = [_Choice(text)]

    class _Completions:
        def create(self, **kwargs):
            captured["create_kwargs"] = kwargs
            if error is not None:
                raise error
            return _Completion(content)

    class _Chat:
        def __init__(self):
            self.completions = _Completions()

    class OpenAI:
        def __init__(self, **kwargs):
            captured["init_kwargs"] = kwargs
            self.chat = _Chat()

    module.OpenAI = OpenAI
    return module


class TestLlm(unittest.TestCase):
    def _import_llm(self):
        for name in ("llm", "llm.client", "openai"):
            sys.modules.pop(name, None)
        from llm.client import LLMUnavailable, llm

        return LLMUnavailable, llm

    def test_missing_key_raises_fast_without_sdk_use(self):
        LLMUnavailable, llm = self._import_llm()
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("OPENROUTER_API_KEY", "LLM_MODEL")
        }
        env["OPENROUTER_API_KEY"] = ""

        def _explode(*args, **kwargs):
            raise AssertionError("must not touch the network")

        fake = types.ModuleType("openai")
        fake.OpenAI = _explode
        start = time.monotonic()
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.dict(sys.modules, {"openai": fake}):
                with self.assertRaises(LLMUnavailable):
                    llm("hi")
        self.assertLess(time.monotonic() - start, 2.0)

    def test_unset_key_raises_without_network(self):
        LLMUnavailable, llm = self._import_llm()
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("OPENROUTER_API_KEY", "LLM_MODEL")
        }

        def _explode(*args, **kwargs):
            raise AssertionError("must not touch the network")

        fake = types.ModuleType("openai")
        fake.OpenAI = _explode
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.dict(sys.modules, {"openai": fake}):
                with self.assertRaises(LLMUnavailable):
                    llm("hi")

    def test_json_mode_returns_dict(self):
        LLMUnavailable, llm = self._import_llm()
        captured = {}
        fake = _make_openai_double(captured, content='{"a": 1}')
        with mock.patch.dict(
            os.environ, {"OPENROUTER_API_KEY": "test-key"}, clear=False
        ):
            with mock.patch.dict(sys.modules, {"openai": fake}):
                result = llm("hi", json_mode=True)
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("a"), 1)

    def test_plain_mode_returns_str(self):
        _, llm = self._import_llm()
        captured = {}
        fake = _make_openai_double(captured, content="hello there")
        with mock.patch.dict(
            os.environ, {"OPENROUTER_API_KEY": "test-key"}, clear=False
        ):
            with mock.patch.dict(sys.modules, {"openai": fake}):
                result = llm("hi")
        self.assertIsInstance(result, str)
        self.assertEqual(result, "hello there")

    def test_sdk_error_translates_to_unavailable(self):
        LLMUnavailable, llm = self._import_llm()
        captured = {}
        fake = _make_openai_double(
            captured, error=TimeoutError("stub latency 30s")
        )
        with mock.patch.dict(
            os.environ, {"OPENROUTER_API_KEY": "test-key"}, clear=False
        ):
            with mock.patch.dict(sys.modules, {"openai": fake}):
                with self.assertRaises(LLMUnavailable):
                    llm("hi")

    def test_client_config_proves_timeout_bound(self):
        _, llm = self._import_llm()
        captured = {}
        fake = _make_openai_double(captured, content="ok")
        env = dict(os.environ)
        env["OPENROUTER_API_KEY"] = "test-key"
        env.pop("OPENROUTER_BASE_URL", None)
        env.pop("LLM_MODEL", None)
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.dict(sys.modules, {"openai": fake}):
                llm("hi")
        init_kwargs = captured["init_kwargs"]
        self.assertEqual(init_kwargs["timeout"], 20.0)
        self.assertEqual(init_kwargs["max_retries"], 0)
        self.assertEqual(
            init_kwargs["base_url"], "https://openrouter.ai/api/v1"
        )
        self.assertLess(init_kwargs["timeout"], 25.0)

    def test_base_url_override_honored(self):
        _, llm = self._import_llm()
        captured = {}
        fake = _make_openai_double(captured, content="ok")
        with mock.patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "test-key",
                "OPENROUTER_BASE_URL": "http://stub.local/v1",
            },
            clear=False,
        ):
            with mock.patch.dict(sys.modules, {"openai": fake}):
                llm("hi")
        self.assertEqual(
            captured["init_kwargs"]["base_url"], "http://stub.local/v1"
        )

    def test_fenced_json_parsed(self):
        _, llm = self._import_llm()
        captured = {}
        fake = _make_openai_double(
            captured, content='```json\n{"a": 1}\n```'
        )
        with mock.patch.dict(
            os.environ, {"OPENROUTER_API_KEY": "test-key"}, clear=False
        ):
            with mock.patch.dict(sys.modules, {"openai": fake}):
                result = llm("hi", json_mode=True)
        self.assertEqual(result.get("a"), 1)


if __name__ == "__main__":
    unittest.main()
