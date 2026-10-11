import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("public_check", Path(__file__).resolve().parents[1] / "scripts" / "check_public.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class LockPublicationTests(unittest.TestCase):
    def test_valid_dependency_versions_are_not_network_addresses(self):
        version = b"10." + b"3.0.9"
        self.assertEqual(checker.inspect("requirements.lock", b"nvidia-cudnn-cu13==" + version + b" \\\n --hash=sha256:abc\n", {"requirements.lock"}), [])

    def test_urls_and_comments_still_reject_private_addresses(self):
        address = b"10." + b"1.2.3"
        for value in [b"# server " + address + b"\n", b"--index-url=http://" + address + b"/simple\n"]:
            self.assertIn(("requirements.lock", "private-network-address"), checker.inspect("requirements.lock", value, {"requirements.lock"}))
