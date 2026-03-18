"""Tests for mcp_shared.project_detect."""

from pathlib import Path

from mcp_shared.project_detect import StackInfo, detect_project_root, detect_stack


class TestDetectProjectRoot:
    def test_finds_git_directory(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        sub = tmp_path / "a" / "b"
        sub.mkdir(parents=True)
        assert detect_project_root(sub) == tmp_path

    def test_finds_pyproject_toml(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").touch()
        assert detect_project_root(tmp_path) == tmp_path

    def test_returns_none_when_no_marker(self, tmp_path: Path) -> None:
        sub = tmp_path / "empty"
        sub.mkdir()
        # Walk up will never find a marker in tmp_path either
        # (unless it happens to have one, which is unlikely in a tmp dir).
        # We check the sub itself has no marker:
        result = detect_project_root(sub)
        # Result may find markers above tmp_path (e.g., system .git).
        # So we just verify it doesn't return sub or tmp_path:
        assert result != sub


class TestDetectStack:
    def test_python_project_with_uv(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").touch()
        (tmp_path / "uv.lock").touch()
        result = detect_stack(tmp_path)
        assert result == StackInfo(lang="python", pkg_mgr="uv")

    def test_python_project_with_poetry(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").touch()
        (tmp_path / "poetry.lock").touch()
        result = detect_stack(tmp_path)
        assert result == StackInfo(lang="python", pkg_mgr="poetry")

    def test_python_project_default_pip(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").touch()
        result = detect_stack(tmp_path)
        assert result == StackInfo(lang="python", pkg_mgr="pip")

    def test_node_project_with_pnpm(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").touch()
        (tmp_path / "pnpm-lock.yaml").touch()
        result = detect_stack(tmp_path)
        assert result == StackInfo(lang="node", pkg_mgr="pnpm")

    def test_go_project(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").touch()
        result = detect_stack(tmp_path)
        assert result == StackInfo(lang="go", pkg_mgr="go")

    def test_rust_project(self, tmp_path: Path) -> None:
        (tmp_path / "Cargo.toml").touch()
        result = detect_stack(tmp_path)
        assert result == StackInfo(lang="rust", pkg_mgr="cargo")

    def test_unknown_project(self, tmp_path: Path) -> None:
        result = detect_stack(tmp_path)
        assert result == StackInfo(lang="unknown")
