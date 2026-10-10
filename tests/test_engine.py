"""SDK contracts: no demo server, no database and no live providers."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from ticket_engine import TicketEngine, EngineError, compare
from ticket_engine import engine, transport
from ticket_engine.rules import CATEGORIES, QUESTIONS


def prediction(category="refund", confidence=.9, complaint=.1):
    return {"model": "test-model", "answers": {
        "category": {"choice": category, "confidence": confidence,
            "probabilities": {key: .96 if key == category else .01 for key in CATEGORIES}},
        "urgency": {"score": 1.8}, "complaint": {"noul": complaint},
        "churn": {"noul": .1}, "refund": {"noul": .9}}, "usage": {"input_tokens": 50}}


class EngineContracts(unittest.TestCase):
    def setUp(self):
        self.verify = patch.object(engine, "verify_checkpoint")
        self.verify_mock = self.verify.start()
        self.addCleanup(self.verify.stop)
        self.agent = Mock()
        self.agent.predict.return_value = prediction()
        self.loader = patch.object(engine, "load_agent", return_value=self.agent)
        self.load_mock = self.loader.start()
        self.addCleanup(self.loader.stop)
        self.remote = patch.object(engine, "request_jev", return_value=prediction())
        self.remote_mock = self.remote.start()
        self.addCleanup(self.remote.stop)

    def test_same_structured_output_from_both_engines_without_input_or_key(self):
        local = TicketEngine("laya", model_path="explicit-model")
        remote = TicketEngine("jev", api_key="synthetic-example-key")
        a = local.classify("Synthetic confidential message", subject="Subject").to_dict()
        b = remote.classify("Synthetic confidential message", subject="Subject").to_dict()
        self.assertEqual(set(a), set(b))
        self.assertEqual(a["input_id"], b["input_id"])
        self.assertEqual(a["rubric_id"], b["rubric_id"])
        for result in (a, b):
            self.assertNotIn("Synthetic confidential message", json.dumps(result))
            self.assertNotIn("synthetic-example-key", json.dumps(result))
            self.assertEqual(result["category"], "refund")
        self.assertEqual(self.agent.predict.call_args.args[:2], self.remote_mock.call_args.args[:2])

    def test_bad_input_never_loads_or_calls_either_engine(self):
        for provider in (TicketEngine("laya", model_path="explicit-model"), TicketEngine("jev", api_key="example-key")):
            for message, subject in [(None, ""), (" ", ""), ("x" * 3001, ""), ("valid", "s" * 121), ("valid", None)]:
                with self.assertRaises(EngineError) as raised:
                    provider.classify(message, subject=subject)
                self.assertEqual(raised.exception.code, "invalid_input")
        self.load_mock.assert_not_called()
        self.remote_mock.assert_not_called()

    def test_lazy_model_load_once_and_instance_state_is_separate(self):
        first = TicketEngine("laya", model_path="first")
        second = TicketEngine("laya", model_path="second")
        self.load_mock.assert_not_called()
        first.classify("one")
        first.classify("two")
        self.assertEqual(self.load_mock.call_count, 1)
        second.classify("three")
        self.assertEqual(self.load_mock.call_count, 2)
        self.assertNotEqual(self.load_mock.call_args_list[0], self.load_mock.call_args_list[1])

    def test_concurrent_calls_on_one_local_engine_are_serialized(self):
        local = TicketEngine("laya", model_path="explicit-model")
        active = 0
        maximum = 0
        def work(*args):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            time.sleep(.02)
            active -= 1
            return prediction()
        self.agent.predict.side_effect = work
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(local.classify, ["one", "two", "three"]))
        self.assertEqual(len(results), 3)
        self.assertEqual(maximum, 1)
        self.assertEqual(self.load_mock.call_count, 1)

    def test_invalid_checkpoint_has_safe_error_and_never_falls_back(self):
        self.verify_mock.side_effect = ValueError("sensitive internal path")
        with self.assertRaises(EngineError) as raised:
            TicketEngine("laya", model_path="missing").classify("text")
        self.assertEqual(raised.exception.code, "invalid_checkpoint")
        self.assertNotIn("sensitive", str(raised.exception))
        self.remote_mock.assert_not_called()
        self.load_mock.assert_not_called()

    def test_invalid_scores_and_missing_fields_are_rejected(self):
        for result in [prediction(confidence=float("nan")), {"answers": {}}, prediction()]:
            if result.get("usage") and result["answers"]["category"]["confidence"] == .9:
                result["answers"]["refund"]["noul"] = True
            self.remote_mock.return_value = result
            with self.assertRaises(EngineError) as raised:
                TicketEngine("jev", api_key="example-key").classify("text")
            self.assertEqual(raised.exception.code, "invalid_response")

    def test_review_is_explicit_and_other_is_not_uncertainty(self):
        self.remote_mock.return_value = prediction("other", confidence=.2)
        result = TicketEngine("jev", api_key="example-key").classify("text")
        self.assertTrue(result.needs_review)
        self.assertEqual(result.review_reasons, ("low_confidence",))
        self.remote_mock.return_value = prediction("other", confidence=.9)
        self.assertFalse(TicketEngine("jev", api_key="example-key").classify("text").needs_review)

    def test_compare_uses_same_input_and_thresholded_decisions(self):
        self.remote_mock.return_value = prediction(complaint=.8)
        result = compare(TicketEngine("laya", model_path="explicit-model"), TicketEngine("jev", api_key="example-key"), "text")
        self.assertEqual(result.differences, ("complaint",))
        self.assertFalse(result.to_dict()["agreement"])
        self.assertEqual(self.remote_mock.call_count, 1)

    def test_provider_failure_is_not_retried(self):
        self.remote_mock.side_effect = transport.ProviderError("Temporary failure", 429)
        with self.assertRaises(EngineError) as raised:
            TicketEngine("jev", api_key="example-key").classify("text")
        self.assertTrue(raised.exception.retryable)
        self.assertEqual(self.remote_mock.call_count, 1)

    def test_changed_rules_are_rejected_before_any_provider_call(self):
        changed = copy.deepcopy(QUESTIONS)
        changed["category"]["instructions"] += " changed"
        with patch.object(engine, "QUESTIONS", changed):
            for provider in (TicketEngine("laya", model_path="explicit-model"), TicketEngine("jev", api_key="example-key")):
                with self.assertRaises(EngineError) as raised:
                    provider.classify("text")
                self.assertEqual(raised.exception.code, "invalid_config")
        self.remote_mock.assert_not_called()
        self.load_mock.assert_not_called()

    def test_explicit_config_rejects_inherited_key_and_header_injection(self):
        with patch.dict(os.environ, TYPESAFE_API_KEY="example-environment-key"):
            for key in (None, "", "key\r\ninjected", "key with space"):
                with self.assertRaises(EngineError):
                    TicketEngine("jev", api_key=key)
        with self.assertRaises(EngineError):
            TicketEngine("laya")
        with self.assertRaises(EngineError):
            TicketEngine("jev", api_key="example-key", timeout=float("nan"))

    def test_normalization_does_not_share_mutable_results_or_rules(self):
        original = copy.deepcopy(QUESTIONS)
        a = TicketEngine("jev", api_key="example-key").classify("text")
        output = a.to_dict()
        output["probabilities"]["refund"] = 0
        self.assertNotEqual(output["probabilities"], a.probabilities)
        self.assertEqual(QUESTIONS, original)


class ImportBoundary(unittest.TestCase):
    def test_plain_import_needs_no_ml_stack_server_database_or_env_changes(self):
        code = '''import os, sys
before = dict(os.environ)
from ticket_engine import TicketEngine
assert os.environ == before
assert not any(name in sys.modules for name in ("torch", "transformers", "server", "sqlite3"))
print("plain import OK")
'''
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
