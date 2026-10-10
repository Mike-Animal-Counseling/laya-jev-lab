"""Publication and personal-workspace isolation regression checks."""
import importlib.util
import json
import os
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import server
from projects.jev import provider as jev
from projects.laya_ft import provider as ft
from test_ab import ServiceCase

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("public_check", ROOT / "scripts/check_public.py")
scanner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scanner)


class Isolation(unittest.TestCase):
    def test_no_inherited_api_key_or_parent_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "demo"
            root.mkdir()
            (root.parent / ".env.local").write_text("TYPESAFE_API_KEY=parent-example-key", encoding="utf-8")
            with patch.object(jev, "ROOT", root), patch.dict(os.environ, TYPESAFE_API_KEY="environment-example-key"):
                self.assertEqual(jev.config()["TYPESAFE_API_KEY"], "")
                self.assertEqual(jev.status()["status"], "unconfigured")
                (root / ".env.local").write_text("TYPESAFE_API_KEY=own-example-key", encoding="utf-8")
                self.assertEqual(jev.config()["TYPESAFE_API_KEY"], "own-example-key")

    def test_only_two_models_and_explicit_synthetic_identities(self):
        self.assertEqual(set(server.PROVIDERS), {"laya-ft", "jev"})
        for ticket in server.seed_tickets():
            self.assertEqual(set(ticket["runs"]), {"laya-ft", "jev"})
            self.assertTrue(ticket["customer"].startswith("Demo user"))
            self.assertTrue(ticket["company"].startswith("Example team"))
            self.assertIsNone(ticket["reference"])
        self.assertEqual(ft.MODEL, ROOT / "models/ticket-finetuned-v5")

    def test_scanner_blocks_private_files_and_never_echoes_the_value(self):
        fake = ("ghp_" + "x" * 36).encode()
        errors = scanner.inspect("notes.txt", fake, {"notes.txt"})
        self.assertIn(("notes.txt", "github-token"), errors)
        self.assertNotIn(fake.decode(), str(errors))
        self.assertIn((".env.local", "not-allowlisted"), scanner.inspect(".env.local", b"", {".env.example"}))
        self.assertTrue(scanner.inspect(".env.example", b"TYPESAFE_API_KEY=example", {".env.example"}))
        for key in ("ZENDESK_OAUTH_TOKEN", "ZENDESK_API_TOKEN", "TICKET_API_TOKEN", "MAIL_IMAP_PASSWORD", "ZENDESK_EMAIL", "MAIL_IMAP_USER"):
            self.assertTrue(scanner.inspect(".env.example", (key + "=example").encode(), {".env.example"}))

    def test_allowlist_cannot_authorize_runtime_state(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(scanner, "ROOT", Path(tmp)):
            (Path(tmp) / "release-files.json").write_text(json.dumps(["var/tickets.sqlite3"]), encoding="utf-8")
            with self.assertRaises(ValueError):
                scanner.allowlist()

    def test_git_privacy_identity_requires_noreply_without_echoing_email(self):
        with patch.object(scanner, "git", return_value=b"Public Alias <author@example.invalid> 1 +0000"):
            errors = scanner.check_identity()
            self.assertTrue(errors)
            self.assertNotIn("author@example.invalid", str(errors))
        with patch.object(scanner, "git", return_value=b"Public Alias <123+public-alias@users.noreply.github.com> 1 +0000"):
            self.assertEqual(scanner.check_identity(), [])

    def test_staged_bytes_are_scanned_even_after_worktree_secret_is_removed(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(scanner, "ROOT", Path(tmp)), \
                patch.dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull, GIT_CONFIG_NOSYSTEM="1"):
            root = Path(tmp)
            subprocess.run(["git", "-C", tmp, "init", "-q", "--template="], check=True, capture_output=True)
            (root / "release-files.json").write_text(json.dumps(["release-files.json", "notes.md"]), encoding="utf-8")
            (root / "notes.md").write_text("ghp_" + "x" * 36, encoding="utf-8")
            subprocess.run(["git", "-C", tmp, "add", "."], check=True, capture_output=True)
            (root / "notes.md").write_text("Clean worktree", encoding="utf-8")
            self.assertEqual(scanner.check(), [])
            self.assertIn(("notes.md", "github-token"), scanner.check(staged=True))


class RemovedBaseline(ServiceCase):
    def test_legacy_provider_is_not_an_api_backdoor(self):
        self.call("tickets?provider=laya", expected=400)
        self.call("analyze", {"id": "TK-1042", "provider": "laya"}, expected=400)
        self.local_mock.assert_not_called()
        self.remote_mock.assert_not_called()
