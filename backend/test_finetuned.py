"""Offline model integrity/import tests with temporary, non-executable fake weights."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import Mock, patch

import server
from projects.laya_ft import provider as ft
from projects.laya_ft import import_checkpoint as importer


class FinetunedProvider(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="v5-contract-")
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "model"
        for name in ft.REQUIRED_FILES:
            target = self.path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps({"model_type": "modernbert"} if name == "encoder/config.json" else {}), encoding="utf-8")
        self.record = copy.deepcopy(ft.EXPECTED)
        self.record["files"] = {n: {"sha256": ft.digest(self.path / n)} for n in ft.REQUIRED_FILES}
        self.record["checkpoint_sha256"] = self.record["files"]["model.safetensors"]["sha256"]
        expected = patch.object(ft, "EXPECTED", copy.deepcopy(self.record))
        expected.start()
        self.addCleanup(expected.stop)
        self.write_manifest()

    def write_manifest(self):
        (self.path / "training_manifest.json").write_text(json.dumps(self.record), encoding="utf-8")

    def archive(self, extra=None):
        path = self.path.parent / "model.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for name in (*ft.REQUIRED_FILES, "training_manifest.json"):
                archive.write(self.path / name, name)
            for name in importer.NOTICES:
                archive.write(importer.PROJECT / name, name)
            if extra:
                archive.writestr(extra, "untrusted")
        return path

    def test_reviewed_identity_and_all_task_rules_are_required(self):
        self.assertEqual(ft.verify_checkpoint(self.path, server.QUESTIONS), self.record)
        for field, value in [("artifact_version", 4), ("artifact_version", True), ("schema_version", 1),
                             ("trained_fields", ["category"]), ("training_steps", 0), ("checkpoint_sha256", "changed")]:
            with self.subTest(field=field):
                old = self.record[field]
                self.record[field] = value
                self.write_manifest()
                with self.assertRaises(ValueError):
                    ft.verify_checkpoint(self.path, server.QUESTIONS)
                self.record[field] = old
        self.write_manifest()
        changed = copy.deepcopy(server.QUESTIONS)
        changed["urgency"]["instructions"] += " changed"
        with self.assertRaises(ValueError):
            ft.verify_checkpoint(self.path, changed)

    def test_modified_weights_and_rewritten_manifest_cannot_bypass_pinned_hash(self):
        (self.path / "model.safetensors").write_bytes(b"tampered")
        self.record["files"]["model.safetensors"]["sha256"] = ft.digest(self.path / "model.safetensors")
        self.record["checkpoint_sha256"] = self.record["files"]["model.safetensors"]["sha256"]
        self.write_manifest()
        with self.assertRaises(ValueError):
            ft.verify_checkpoint(self.path, server.QUESTIONS)

    def test_missing_checkpoint_never_invokes_another_provider(self):
        with patch.object(ft, "MODEL", self.path / "missing"), patch.object(ft, "agent", None), \
                patch.object(ft, "manifest", None), patch.dict(ft.model_status):
            ft.load(server.QUESTIONS)
            self.assertEqual(ft.model_status["status"], "unconfigured")
            with self.assertRaises(RuntimeError):
                ft.predict({}, server.QUESTIONS)

    def test_unreadable_checkpoint_is_safe_error(self):
        with patch.object(ft, "MODEL", self.path), patch.object(ft, "agent", None), \
                patch.object(ft, "manifest", None), patch.dict(ft.model_status), \
                patch.object(Path, "is_file", side_effect=PermissionError("denied")):
            ft.load(server.QUESTIONS)
            self.assertEqual(ft.model_status["status"], "error")
            self.assertIsNone(ft.agent)

    def test_all_five_outputs_are_local_and_keep_provenance(self):
        agent = Mock()
        agent.predict.return_value = {"answers": {key: {} for key in ft.FULL_FIELDS}, "usage": {"input_tokens": 30}}
        with patch.object(ft, "agent", agent), patch.object(ft, "manifest", self.record), patch.dict(ft.model_status, status="ready"):
            result = ft.predict({"message": "Synthetic ticket"}, server.QUESTIONS)
            self.assertEqual(result["field_sources"], {key: "laya-ft" for key in ft.FULL_FIELDS})
            self.assertEqual(result["checkpoint_sha256"], self.record["checkpoint_sha256"])
            agent.predict.return_value["answers"].pop("refund")
            with self.assertRaises(RuntimeError):
                ft.predict({}, server.QUESTIONS)

    def test_archive_import_is_verified_and_never_overwrites(self):
        workspace = self.path.parent / "workspace"
        archive = self.archive()
        with patch.object(importer, "WORKSPACE", workspace):
            importer.import_archive(archive)
            with self.assertRaises(FileExistsError):
                importer.import_archive(archive)
        self.assertTrue((workspace / "models/ticket-finetuned-v5/model.safetensors").is_file())

    def test_unsafe_or_extra_archive_members_rejected_before_extraction(self):
        for extra in ("../escape", "/absolute", chr(67) + ":/absolute", "notes.txt", "tokenizer/../../escape"):
            with zipfile.ZipFile(self.archive(extra)) as opened, self.assertRaises(ValueError):
                importer.validate_members(opened)

    def test_manifest_cannot_authorize_extra_files(self):
        self.record["files"]["notes.txt"] = {"sha256": "anything"}
        self.write_manifest()
        with zipfile.ZipFile(self.archive("notes.txt")) as opened, self.assertRaises(ValueError):
            importer.validate_members(opened)

    def test_hash_failure_leaves_no_installed_model(self):
        (self.path / "model.safetensors").write_bytes(b"tampered")
        workspace = self.path.parent / "workspace"
        with patch.object(importer, "WORKSPACE", workspace), self.assertRaises(ValueError):
            importer.import_archive(self.archive())
        self.assertEqual(list((workspace / "models").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
