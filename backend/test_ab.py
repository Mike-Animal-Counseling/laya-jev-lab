"""Isolated contract tests. Fake adapters are test-only; no production data or API calls."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import server
from waitress import create_server
from classification import RUBRIC_ID, normalize, paired_summary
from projects.jev import provider as jev
from ticket_engine import transport


def prediction(category="sales", confidence=.9):
    return {"model": "test-model", "answers": {
        "category": {"choice": category, "confidence": confidence,
                     "probabilities": {key: .96 if key == category else .01 for key in server.CATEGORIES}},
        "urgency": {"score": .2}, "complaint": {"noul": .1}, "churn": {"noul": .1}, "refund": {"noul": .1}},
        "usage": {"input_tokens": 123}}


class ServiceCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="model-lab-test-")
        server.DATA = Path(cls.temporary.name) / "data.json"
        cls.http = create_server(server.application, host="127.0.0.1", port=0, threads=4)
        cls.thread = threading.Thread(target=cls.http.run, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.http.effective_port}/api/"

    @classmethod
    def tearDownClass(cls):
        cls.http.close(); cls.http.task_dispatcher.shutdown(); cls.thread.join(3); cls.temporary.cleanup()

    def setUp(self):
        server.tickets = server.seed_tickets()
        server.generation = 0
        server.limiter = server.WriteLimiter()
        self.ready = patch.object(server, "statuses", return_value={"laya-ft": {"status": "ready"}, "jev": {"status": "ready"}})
        self.ready.start(); self.addCleanup(self.ready.stop)
        self.local = patch.object(server.finetuned_provider, "predict", side_effect=lambda state, questions: prediction("sales"))
        self.remote = patch.object(server.jev_provider, "predict", side_effect=lambda state, questions: prediction("account"))
        self.local_mock = self.local.start(); self.remote_mock = self.remote.start()
        self.addCleanup(self.local.stop); self.addCleanup(self.remote.stop)

    def call(self, path, data=None, expected=200, origin=None):
        headers = {"Content-Type": "application/json", "X-CSRF-Token": server.CSRF_TOKEN}
        if origin: headers["Origin"] = origin
        request = Request(self.base + path, headers=headers, data=None if data is None else json.dumps(data).encode())
        try:
            with urlopen(request, timeout=5) as response:
                status, result = response.status, json.load(response)
        except HTTPError as exc:
            status, result = exc.code, json.load(exc)
        self.assertEqual(status, expected, result)
        return result


class ABContracts(ServiceCase):
    def test_providers_receive_identical_input_and_keep_separate_results(self):
        self.call("analyze", {"id": "TK-1042", "provider": "laya-ft"})
        result = self.call("analyze", {"id": "TK-1042", "provider": "jev"})["ticket"]
        self.assertEqual(result["analysis"]["category"], "account")
        self.assertEqual(result["runs"]["laya-ft"]["analysis"]["category"], "sales")
        self.assertEqual(self.local_mock.call_args, self.remote_mock.call_args)
        self.assertEqual(self.call("tickets?provider=laya-ft")["tickets"][6]["analysis"]["category"], "sales")
        stored = server.TicketStore(server.DATA).load()
        self.assertIsNone(stored[6]["reference"])
        self.assertEqual(stored[6]["runs"]["jev"]["analysis"]["rubric_id"], RUBRIC_ID)

    def test_low_confidence_needs_explicit_team_and_assignment_isolated(self):
        self.local_mock.side_effect = lambda state, questions: prediction("sales", .2)
        self.call("analyze", {"id": "TK-1042"})
        self.call("assign", {"id": "TK-1042"}, 409)
        result = self.call("assign", {"id": "TK-1042", "team": "售前顾问"})["ticket"]
        self.assertEqual(result["status"], "assigned")
        self.assertEqual(result["runs"]["jev"]["status"], "pending")
        self.assertIsNone(result["reference"])
        self.call("analyze", {"id": "TK-1042"}, 409)
        result = self.call("analyze", {"id": "TK-1042", "evaluation": True})["ticket"]
        self.assertEqual((result["status"], result["team"]), ("assigned", "售前顾问"))

    def test_accuracy_uses_only_labelled_current_pairs(self):
        self.call("analyze", {"id": "TK-1042"})
        self.call("reference", {"id": "TK-1042", "category": "sales"})
        self.assertEqual(self.call("tickets")["summary"]["labelled"], 0)
        self.call("analyze", {"id": "TK-1042", "provider": "jev"})
        summary = self.call("tickets")["summary"]
        self.assertEqual((summary["labelled"], summary["laya"]["correct"], summary["jev"]["correct"]), (1, 1, 0))
        server.tickets[6]["runs"]["laya-ft"]["analysis"]["rubric_id"] = "old"
        self.assertEqual(paired_summary(server.tickets)["paired"], 0)

    def test_invalid_response_does_not_replace_previous_result(self):
        before = self.call("analyze", {"id": "TK-1042"})["ticket"]["analysis"]
        self.local_mock.side_effect = lambda state, questions: {"answers": {}}
        self.call("analyze", {"id": "TK-1042"}, 502)
        self.assertEqual(server.tickets[6]["runs"]["laya-ft"]["analysis"], before)

    def test_reset_discards_in_flight_results(self):
        entered, release = threading.Event(), threading.Event()
        def slow(state, questions):
            entered.set(); release.wait(4); return prediction()
        self.remote_mock.side_effect = slow
        responses = []
        def run(): responses.append(self.call("analyze", {"id": "TK-1042", "provider": "jev"}, 409))
        worker = threading.Thread(target=run); worker.start()
        self.assertTrue(entered.wait(2))
        self.call("reset", {})
        release.set(); worker.join(3)
        self.assertTrue(responses)
        self.assertIsNone(server.tickets[6]["runs"]["jev"]["analysis"])

    def test_missing_key_and_bad_requests_never_call_provider(self):
        with patch.object(server, "statuses", return_value={"jev": {"status": "unconfigured"}}):
            self.call("analyze", {"id": "TK-1042", "provider": "jev"}, 503)
        self.remote_mock.assert_not_called()
        self.call("analyze", {"id": "TK-1042", "provider": "unknown"}, 400)
        self.call("reference", {"id": "TK-1042", "category": "unknown"}, 400)
        self.call("reset", {}, 403, "https://untrusted.example")



    def test_unconnected_finetuned_slot_does_not_fall_back(self):
        with patch.object(server, "statuses", return_value={"laya-ft": server.finetuned_provider.model_status}):
            self.call("analyze", {"id": "TK-1042", "provider": "laya-ft"}, 503)
        self.local_mock.assert_not_called()
        self.remote_mock.assert_not_called()
        self.assertIsNone(self.call("tickets?provider=laya-ft")["tickets"][6]["analysis"])



class Validation(unittest.TestCase):
    def test_nonfinite_and_inconsistent_probabilities_rejected(self):
        for value in (float("nan"), float("inf"), True, -1, 1.1):
            result = prediction(); result["answers"]["category"]["confidence"] = value
            with self.assertRaises(ValueError): normalize(result, "jev", 10, {}, "00:00")
        result = prediction(); result["answers"]["category"]["probabilities"]["sales"] = .2
        with self.assertRaises(ValueError): normalize(result, "jev", 10, {}, "00:00")

    def test_jev_transport_uses_documented_contract(self):
        captured = {}
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit): return json.dumps(prediction()).encode()
        class Opener:
            def open(self, request, timeout):
                captured.update(url=request.full_url, body=json.loads(request.data), auth=request.get_header("Authorization"), timeout=timeout)
                return Response()
        with patch.object(jev, "config", return_value={"TYPESAFE_API_KEY": "test-only-not-real", "JEV_MODEL": "jev-1.13.0"}), patch.object(transport, "build_opener", return_value=Opener()):
            jev.predict({"message": "fictional ticket"}, server.QUESTIONS)
        self.assertEqual(captured["url"], "https://api.typesafe.ai/v1/systemone")
        self.assertEqual(captured["body"]["questions"], server.QUESTIONS)
        self.assertEqual(captured["body"]["model"], "jev-1.13.0")
        self.assertEqual(captured["auth"], "Bearer test-only-not-real")


if __name__ == "__main__":
    unittest.main(verbosity=2)
