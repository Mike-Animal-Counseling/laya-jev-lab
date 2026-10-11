import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("public_check", Path(__file__).resolve().parents[1] / "scripts" / "check_public.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class LockPublicationTests(unittest.TestCase):
    def test_valid_dependency_versions_are_not_network_addresses(self):
        self.assertEqual(checker.inspect("requirements.lock", b"nvidia-cudnn-cu13==10.3.0.9 \\\n --hash=sha256:abc\n", {"requirements.lock"}), [])

    def test_urls_and_comments_still_reject_private_addresses(self):
        for value in [b"# server 10.1.2.3\n", b"--index-url=http://10.1.2.3/simple\n"]:
            self.assertIn(("requirements.lock", "private-network-address"), checker.inspect("requirements.lock", value, {"requirements.lock"}))
