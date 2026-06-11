"""Artifact 安全校验：SHA-256 完整性验证。

在加载任何 pickle/joblib/onnx 文件前完成校验，防止反序列化 RCE。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


class ArtifactVerificationError(Exception):
    """Bundle 完整性校验失败——不能继续加载。"""


# ── 硬编码 hash 锚点（AirRouter 代码中固定，攻击者无法绕过） ──
MANIFEST_SHA256 = "949b312eb696fe44132176633ceb46f593d42d647b3cd74e1c237b175e6652b4"
RUNTIME_CONFIG_SHA256 = "b49ae2024242bb56a3428e9fde0dfd57ddf2d3cc04f362b1d886e90c1aef965c"
RUNTIME_SRC_TREE_SHA256 = "60a5715b31c49faf07ef0872e53b94a2faadcf588264605ede78217edacda5b2"
OPENSQUILLA_COMMIT = "5409a22a5205846a6f9998e2d361cf286d8caa8d"

# 不允许出现在 bundle 中的文件后缀
_UNEXPECTED_BINARY_SUFFIXES = {".so", ".dylib", ".pyd"}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


class ArtifactVerifier:
    """Bundle 完整性校验器。

    校验顺序：
    1. manifest 自身 SHA-256
    2. runtime config SHA-256
    3. runtime_src 源码树 SHA-256
    4. manifest 所列各文件的存在性 + 大小 + SHA-256
    5. 全 bundle symlink 扫描
    6. 意外 binary 扫描
    """

    def __init__(self, bundle_dir: Path):
        self._bundle_dir = bundle_dir

    def verify_all(self) -> None:
        """校验全部。任一失败抛 ArtifactVerificationError。"""
        self.verify_manifest_integrity()
        self.verify_runtime_config()
        self.verify_runtime_src_tree()
        self._check_symlinks_and_binaries()
        self.verify_artifact_files()

    def verify_manifest_integrity(self) -> None:
        """验证 artifact_manifest.json 自身的 SHA-256。"""
        manifest_path = self._bundle_dir / "artifact_manifest.json"
        if not manifest_path.exists():
            raise ArtifactVerificationError(f"manifest not found: {manifest_path}")
        if manifest_path.is_symlink():
            raise ArtifactVerificationError(f"manifest is a symlink: {manifest_path}")
        actual = _sha256_file(manifest_path)
        if actual != MANIFEST_SHA256:
            raise ArtifactVerificationError(
                f"manifest SHA-256 mismatch: expected {MANIFEST_SHA256}, got {actual}"
            )

    def verify_runtime_config(self) -> None:
        """验证 router.runtime.yaml 的 SHA-256。"""
        config_path = self._bundle_dir / "router.runtime.yaml"
        if not config_path.exists():
            raise ArtifactVerificationError(f"runtime config not found: {config_path}")
        if config_path.is_symlink():
            raise ArtifactVerificationError(f"runtime config is a symlink: {config_path}")
        actual = _sha256_file(config_path)
        if actual != RUNTIME_CONFIG_SHA256:
            raise ArtifactVerificationError(
                f"runtime config SHA-256 mismatch: expected {RUNTIME_CONFIG_SHA256}, got {actual}"
            )

    def verify_runtime_src_tree(self) -> None:
        """验证 runtime_src/ 下所有 .py 文件的树 hash。

        计算规则：按相对路径排序，拼接 relative_path + "\\0" + sha256(file) + "\\n"，
        再对整体取 SHA-256。
        """
        src_dir = self._bundle_dir / "runtime_src"
        if not src_dir.exists():
            raise ArtifactVerificationError(f"runtime_src not found: {src_dir}")

        py_files: list[Path] = sorted(src_dir.rglob("*.py"))
        if not py_files:
            raise ArtifactVerificationError("runtime_src contains no .py files")

        lines: list[str] = []
        for f in py_files:
            rel = f.relative_to(src_dir).as_posix()
            file_hash = _sha256_file(f)
            lines.append(f"{rel}\0{file_hash}\n")

        combined = "".join(lines)
        tree_hash = hashlib.sha256(combined.encode("utf-8")).hexdigest()
        if tree_hash != RUNTIME_SRC_TREE_SHA256:
            raise ArtifactVerificationError(
                f"runtime_src tree SHA-256 mismatch: expected {RUNTIME_SRC_TREE_SHA256}, got {tree_hash}"
            )

    def verify_artifact_files(self) -> None:
        """校验 manifest 所列各文件的存在性 + 大小 + SHA-256。"""
        manifest_path = self._bundle_dir / "artifact_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        for entry in manifest.get("files", []):
            rel_path = entry["path"]
            expected_size = entry["size_bytes"]
            expected_hash = entry["sha256"]
            file_path = self._bundle_dir / rel_path

            if not file_path.exists():
                raise ArtifactVerificationError(f"artifact file missing: {rel_path}")
            if file_path.is_symlink():
                raise ArtifactVerificationError(f"artifact file is a symlink: {rel_path}")

            actual_size = file_path.stat().st_size
            if actual_size != expected_size:
                raise ArtifactVerificationError(
                    f"artifact file size mismatch: {rel_path} "
                    f"expected {expected_size}, got {actual_size}"
                )

            actual_hash = _sha256_file(file_path)
            if actual_hash != expected_hash:
                raise ArtifactVerificationError(
                    f"artifact file SHA-256 mismatch: {rel_path} "
                    f"expected {expected_hash}, got {actual_hash}"
                )

    def _check_symlinks_and_binaries(self) -> None:
        """拒绝 bundle 中的 symlink 和意外 binary 文件。"""
        for path in self._bundle_dir.rglob("*"):
            if path.is_symlink():
                raise ArtifactVerificationError(f"symlink found in bundle: {path}")
            if path.is_file() and path.suffix in _UNEXPECTED_BINARY_SUFFIXES:
                raise ArtifactVerificationError(
                    f"unexpected binary file in bundle: {path}"
                )
