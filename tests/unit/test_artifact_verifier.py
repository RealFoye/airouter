"""Unit tests for artifact_verifier module.

Uses tmp_path to construct fake bundles — no real bundle dependency.
Monkeypatches hash anchor constants so fake bundles can pass verification.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from airouter.engine.complexity.artifact_verifier import (
    ArtifactVerificationError,
    ArtifactVerifier,
    _sha256_file,
)


def _write_file(path: Path, content: bytes | str) -> Path:
    if isinstance(content, str):
        content = content.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _compute_tree_hash(src_dir: Path) -> str:
    """Compute the runtime_src tree hash matching verifier logic."""
    py_files = sorted(src_dir.rglob("*.py"))
    lines = []
    for f in py_files:
        rel = f.relative_to(src_dir).as_posix()
        file_hash = _sha256_file(f)
        lines.append(f"{rel}\0{file_hash}\n")
    combined = "".join(lines)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


@pytest.fixture
def fake_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a minimal fake bundle with matching hashes."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    # runtime_src with one .py file
    src_dir = bundle / "runtime_src" / "src" / "router"
    src_dir.mkdir(parents=True)
    py_content = "# fake module\n"
    _write_file(src_dir / "core.py", py_content)
    _write_file(src_dir / "__init__.py", "")

    # Compute real hashes for the fake content
    manifest_content = {
        "schema_version": 1,
        "bundle": "fake",
        "files": [
            {
                "path": "model.bin",
                "size_bytes": 5,
                "sha256": _sha256_file(_write_file(bundle / "model.bin", b"hello")),
                "kind": "lightgbm_model",
            }
        ],
    }
    manifest_json = json.dumps(manifest_content, indent=2)
    _write_file(bundle / "artifact_manifest.json", manifest_json)

    runtime_config = "route_classes: [R0, R1, R2, R3]\n"
    _write_file(bundle / "router.runtime.yaml", runtime_config)

    # Monkeypatch the hash anchors to match our fake content
    import airouter.engine.complexity.artifact_verifier as av

    monkeypatch.setattr(av, "MANIFEST_SHA256", _sha256_file(bundle / "artifact_manifest.json"))
    monkeypatch.setattr(av, "RUNTIME_CONFIG_SHA256", _sha256_file(bundle / "router.runtime.yaml"))
    tree_hash = _compute_tree_hash(bundle / "runtime_src")
    monkeypatch.setattr(av, "RUNTIME_SRC_TREE_SHA256", tree_hash)

    return bundle


class TestVerifyAll:
    def test_all_pass(self, fake_bundle: Path):
        verifier = ArtifactVerifier(fake_bundle)
        verifier.verify_all()  # should not raise

    def test_missing_manifest(self, tmp_path: Path):
        bundle = tmp_path / "empty"
        bundle.mkdir()
        verifier = ArtifactVerifier(bundle)
        with pytest.raises(ArtifactVerificationError, match="manifest not found"):
            verifier.verify_manifest_integrity()


class TestVerifyManifestIntegrity:
    def test_manifest_symlink_rejected(self, fake_bundle: Path, tmp_path: Path):
        real = fake_bundle / "artifact_manifest.json"
        link = tmp_path / "link_manifest.json"
        link.symlink_to(real)
        # Replace manifest with symlink
        real.unlink()
        real.symlink_to(link)
        verifier = ArtifactVerifier(fake_bundle)
        with pytest.raises(ArtifactVerificationError, match="symlink"):
            verifier.verify_manifest_integrity()

    def test_manifest_tampered(self, fake_bundle: Path):
        manifest = fake_bundle / "artifact_manifest.json"
        manifest.write_text('{"tampered": true}')
        verifier = ArtifactVerifier(fake_bundle)
        with pytest.raises(ArtifactVerificationError, match="SHA-256 mismatch"):
            verifier.verify_manifest_integrity()


class TestVerifyRuntimeConfig:
    def test_config_symlink_rejected(self, fake_bundle: Path, tmp_path: Path):
        real = fake_bundle / "router.runtime.yaml"
        link = tmp_path / "link_config.yaml"
        link.symlink_to(real)
        real.unlink()
        real.symlink_to(link)
        verifier = ArtifactVerifier(fake_bundle)
        with pytest.raises(ArtifactVerificationError, match="symlink"):
            verifier.verify_runtime_config()

    def test_config_missing(self, fake_bundle: Path):
        (fake_bundle / "router.runtime.yaml").unlink()
        verifier = ArtifactVerifier(fake_bundle)
        with pytest.raises(ArtifactVerificationError, match="not found"):
            verifier.verify_runtime_config()


class TestVerifyRuntimeSrcTree:
    def test_tree_hash_match(self, fake_bundle: Path):
        verifier = ArtifactVerifier(fake_bundle)
        verifier.verify_runtime_src_tree()  # should not raise

    def test_tree_hash_mismatch(self, fake_bundle: Path):
        # Modify a .py file after hash was computed
        (fake_bundle / "runtime_src" / "src" / "router" / "core.py").write_text("# modified\n")
        verifier = ArtifactVerifier(fake_bundle)
        with pytest.raises(ArtifactVerificationError, match="tree SHA-256 mismatch"):
            verifier.verify_runtime_src_tree()

    def test_no_runtime_src(self, tmp_path: Path):
        bundle = tmp_path / "no_src"
        bundle.mkdir()
        verifier = ArtifactVerifier(bundle)
        with pytest.raises(ArtifactVerificationError, match="runtime_src not found"):
            verifier.verify_runtime_src_tree()


class TestVerifyArtifactFiles:
    def test_missing_file(self, fake_bundle: Path):
        (fake_bundle / "model.bin").unlink()
        verifier = ArtifactVerifier(fake_bundle)
        with pytest.raises(ArtifactVerificationError, match="missing"):
            verifier.verify_artifact_files()

    def test_wrong_size(self, fake_bundle: Path):
        (fake_bundle / "model.bin").write_bytes(b"hello world")  # 11 bytes instead of 5
        verifier = ArtifactVerifier(fake_bundle)
        with pytest.raises(ArtifactVerificationError, match="size mismatch"):
            verifier.verify_artifact_files()

    def test_wrong_hash(self, fake_bundle: Path):
        # Same size, different content
        (fake_bundle / "model.bin").write_bytes(b"world")
        verifier = ArtifactVerifier(fake_bundle)
        with pytest.raises(ArtifactVerificationError, match="SHA-256 mismatch"):
            verifier.verify_artifact_files()

    def test_artifact_symlink_rejected(self, fake_bundle: Path, tmp_path: Path):
        # Create a copy first, then replace original with symlink to copy
        copy = tmp_path / "model_copy.bin"
        copy.write_bytes((fake_bundle / "model.bin").read_bytes())
        (fake_bundle / "model.bin").unlink()
        (fake_bundle / "model.bin").symlink_to(copy)
        verifier = ArtifactVerifier(fake_bundle)
        with pytest.raises(ArtifactVerificationError, match="symlink"):
            verifier.verify_artifact_files()


class TestSymlinkAndBinaryRejection:
    def test_symlink_in_bundle_rejected(self, fake_bundle: Path, tmp_path: Path):
        target = tmp_path / "target.txt"
        target.write_text("target")
        link = fake_bundle / "unexpected_link"
        link.symlink_to(target)
        verifier = ArtifactVerifier(fake_bundle)
        with pytest.raises(ArtifactVerificationError, match="symlink found"):
            verifier._check_symlinks_and_binaries()

    def test_unexpected_binary_rejected(self, fake_bundle: Path):
        (fake_bundle / "evil.so").write_bytes(b"\x7fELF")
        verifier = ArtifactVerifier(fake_bundle)
        with pytest.raises(ArtifactVerificationError, match="unexpected binary"):
            verifier._check_symlinks_and_binaries()

    def test_dylib_rejected(self, fake_bundle: Path):
        (fake_bundle / "evil.dylib").write_bytes(b"\x00")
        verifier = ArtifactVerifier(fake_bundle)
        with pytest.raises(ArtifactVerificationError, match="unexpected binary"):
            verifier._check_symlinks_and_binaries()

    def test_pyd_rejected(self, fake_bundle: Path):
        (fake_bundle / "evil.pyd").write_bytes(b"\x00")
        verifier = ArtifactVerifier(fake_bundle)
        with pytest.raises(ArtifactVerificationError, match="unexpected binary"):
            verifier._check_symlinks_and_binaries()
