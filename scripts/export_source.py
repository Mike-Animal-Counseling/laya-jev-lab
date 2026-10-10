"""Export only inspected source files, without Git history or runtime state."""
import argparse
import hashlib
from pathlib import Path
import zipfile

from check_public import ROOT, allowlist, check


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if check():
        parser.error("Public source check failed; run scripts/check_public.py for filenames")
    output = args.destination.resolve()
    if output.is_relative_to(ROOT):
        parser.error("Choose a destination outside the source directory")
    # Exclusive creation prevents overwriting a previous release or unrelated file.
    with output.open("xb") as stream, zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(allowlist()):
            info = zipfile.ZipInfo("laya-jev-lab/" + name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100755 if name == ".githooks/pre-commit" else 0o100644) << 16
            archive.writestr(info, (ROOT / name).read_bytes())
    print("Source ZIP created. SHA256:", hashlib.sha256(output.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
