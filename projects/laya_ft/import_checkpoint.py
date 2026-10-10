"""Import the Kaggle export ZIP without overwriting any existing checkpoint."""
import argparse
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import tempfile
import zipfile

PROJECT = Path(__file__).resolve().parents[2]
WORKSPACE = PROJECT
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "backend"))
from projects.laya_ft.provider import REQUIRED_FILES, verify_checkpoint
from rubric import QUESTIONS

DESTINATION = WORKSPACE / "models/ticket-finetuned-v5"
MAX_UNCOMPRESSED_BYTES = 1024 ** 3
NOTICES = ("LICENSE", "NOTICE.md", "MODEL_CARD.md", "licenses/mmbert-MIT.txt")


def validate_members(archive):
    files = {}
    total = 0
    for item in archive.infolist():
        name = item.filename
        parts = PurePosixPath(name).parts
        if (not name or "\\" in name or ":" in name or name.startswith("/")
                or ".." in parts or "." in parts or "//" in name
                or stat.S_ISLNK(item.external_attr >> 16) or item.flag_bits & 1):
            raise ValueError("Unsafe or encrypted ZIP entry")
        if item.is_dir():
            continue
        normalized = name.casefold()
        if normalized in files:
            raise ValueError("Duplicate ZIP entry")
        files[normalized] = item
        total += item.file_size
    if total > MAX_UNCOMPRESSED_BYTES or len(files) > 100:
        raise ValueError("Checkpoint ZIP exceeds import limits")
    if "training_manifest.json" not in files:
        raise ValueError("ZIP must contain training_manifest.json at its root")
    manifest_entry = files["training_manifest.json"]
    if manifest_entry.file_size > 1024 * 1024:
        raise ValueError("Oversized manifest")
    manifest = json.loads(archive.read(manifest_entry))
    listed = manifest.get("files", {})
    if not isinstance(listed, dict) or not all(isinstance(name, str) for name in listed):
        raise ValueError("Invalid manifest files")
    if set(listed) != set(REQUIRED_FILES):
        raise ValueError("Archive must contain only the reviewed inference files")
    allowed = {name.casefold() for name in (*REQUIRED_FILES, "training_manifest.json", *NOTICES)}
    if set(files) != allowed:
        raise ValueError("ZIP contains unlisted or missing files")
    for name in NOTICES:
        if files[name.casefold()].file_size > 128 * 1024:
            raise ValueError("Oversized notice")
        if archive.read(files[name.casefold()]) != (PROJECT / name).read_bytes():
            raise ValueError("Artifact notice does not match source release")
    return list(files.values())


def import_archive(source):
    with zipfile.ZipFile(source) as archive:
        members = validate_members(archive)
        entry = next(item for item in members if item.filename.casefold() == "training_manifest.json")
        header = json.loads(archive.read(entry))
    full = header.get("schema_version") == 2
    version = header.get("artifact_version", 2 if full else 1)
    if type(version) is not int or (not full or version != 5):
        raise ValueError("Unsupported checkpoint artifact version")
    slot = f"ticket-finetuned-v{version}"
    destination = (WORKSPACE / "models" / slot if full else DESTINATION).resolve()
    models = (WORKSPACE / "models").resolve()
    model_path = WORKSPACE / "models"
    if any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
           for p in [model_path, *model_path.parents]):
        raise ValueError("Linked model directories are not accepted")
    if destination.parent != models or destination.name != slot:
        raise ValueError("Import destination must be the finetuned model slot")
    if destination.exists():
        raise FileExistsError("Finetuned checkpoint already exists; no files were overwritten")
    models.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".laya-ft-import-", dir=models)).resolve()
    try:
        with zipfile.ZipFile(source) as archive:
            members = validate_members(archive)
            for item in members:
                target = (staging / item.filename).resolve()
                if not target.is_relative_to(staging):
                    raise ValueError("ZIP entry escapes staging directory")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as src, target.open("xb") as dst:
                    shutil.copyfileobj(src, dst)
        record = verify_checkpoint(staging, QUESTIONS)
        # Atomic same-volume rename; Windows refuses an existing destination.
        if destination.exists():
            raise FileExistsError("Finetuned checkpoint appeared during import")
        staging.rename(destination)
        return record
    finally:
        if staging.exists():
            if staging.parent != models or not staging.name.startswith(".laya-ft-import-"):
                raise RuntimeError("Refusing cleanup outside import staging")
            shutil.rmtree(staging)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="Kaggle exported checkpoint ZIP")
    args = parser.parse_args()
    try:
        record = import_archive(args.archive.resolve())
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        parser.exit(1, f"Import failed: {exc}\n")
    version = record.get("artifact_version", 2 if record["schema_version"] == 2 else 1)
    print(f"Verified checkpoint imported: {WORKSPACE / 'models' / f'ticket-finetuned-v{version}'}")
    print(f"SHA256: {record['checkpoint_sha256']}")
    print("Restart the local backend to load it. Trained fields: " + ", ".join(record["trained_fields"]))


if __name__ == "__main__":
    main()
