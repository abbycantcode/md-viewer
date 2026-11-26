"""Tests for mdviewer.agentic_env discovery, classification, security denylist, and speed."""

from __future__ import annotations

import threading
from pathlib import Path

from mdviewer import agentic_env


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestAgenticEnv:
    def setup_method(self):
        agentic_env.clear_catalog_cache()

    def test_find_project_root_and_home_boundary(self, tmp_path, monkeypatch):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        (fake_home / ".claude").mkdir()
        monkeypatch.setenv("HOME", str(fake_home))

        # Should not treat $HOME itself as a project root
        loose_file = _write(fake_home / "notes.md", "# Notes\n")
        assert agentic_env.find_project_root(loose_file) is None

        # Project with .git
        repo = fake_home / "code" / "myapp"
        (repo / ".git").mkdir(parents=True)
        nested = _write(repo / "src" / "docs" / "guide.md", "# Guide\n")
        assert agentic_env.find_project_root(nested) == repo

        # Project without .git but with AGENTS.md
        proj2 = fake_home / "code" / "no-git"
        _write(proj2 / "AGENTS.md", "# Agents\n")
        sub = _write(proj2 / "sub" / "doc.md", "# Sub\n")
        assert agentic_env.find_project_root(sub) == proj2

    def test_discovery_classification_filtering_and_banner(self, tmp_path, monkeypatch):
        fake_home = tmp_path / "home"
        repo = tmp_path / "workspace" / "demo-repo"
        (repo / ".git").mkdir(parents=True)
        monkeypatch.setenv("HOME", str(fake_home))

        # Global artifacts across environments
        _write(
            fake_home / ".claude" / "skills" / "refactor" / "SKILL.md",
            "---\nname: refactor-pro\ndescription: Safe refactoring workflow\ntriggers:\n  - refactor\n  - cleanup\n---\n\n# Refactor\n",
        )
        _write(
            fake_home / ".claude" / "skills" / "refactor" / "references" / "patterns.md",
            "# Patterns\n",
        )
        _write(
            fake_home / ".claude" / "skills" / "refactor" / "scripts" / "check.sh",
            "#!/bin/sh\necho ok\n",
        )
        _write(fake_home / ".claude" / "commands" / "review.md", "# Review Command\n")
        _write(fake_home / ".codex" / "AGENTS.md", "# Codex Global Rules\n")
        _write(fake_home / ".codex" / "agents" / "scout" / "agent.md", "# Scout Agent\n")
        _write(fake_home / ".codex" / "rules" / "safety.rules", "allow read\n")
        _write(fake_home / ".agents" / "skills-registry.yaml", "skills: []\n")
        _write(
            fake_home / ".gemini" / "antigravity" / "builtin" / "skills" / "plan" / "SKILL.md",
            "---\nname: planner\ndescription: Stepwise planner\n---\n",
        )
        _write(
            fake_home / ".cursor" / "rules" / "python.mdc",
            "---\ndescription: Python conventions\nglobs: '*.py, tests/*.py'\nalwaysApply: true\n---\n\nUse type hints.\n",
        )
        _write(fake_home / ".config" / "opencode" / "memory" / "notes.md", "# Memory\n")
        _write(fake_home / ".grok" / "skills" / "search" / "SKILL.md", "# Grok Search\n")
        _write(fake_home / ".config" / "CLAUDE.md", "# Global Config Claude\n")
        _write(fake_home / ".antigravity" / "GEMINI.md", "# Antigravity Gemini\n")

        # Project-local artifacts
        _write(repo / "AGENTS.md", "# Repo Guidelines\n")
        _write(repo / "CLAUDE.md", "# Repo Claude\n")
        _write(
            repo / "skills" / "markveil" / "SKILL.md",
            "---\nname: markveil\ndescription: Markveil studio workflows\n---\n\n# Markveil\n",
        )
        _write(repo / "prompts" / "audit.md", "# Audit Prompt\n")

        catalog = agentic_env.discover_agentic_catalog(project_root=repo, force_refresh=True)
        assert catalog.project_root == str(repo)
        assert catalog.scan_ms >= 0.0

        by_rel = {a.rel_path: a for a in catalog.artifacts}

        # Verify Skill metadata + sibling links + banner dict
        refactor = by_rel["~/.claude/skills/refactor/SKILL.md"]
        assert refactor.env_source == "claude"
        assert refactor.scope == "global"
        assert refactor.kind == "skill"
        assert refactor.name == "refactor-pro"
        assert refactor.description == "Safe refactoring workflow"
        assert refactor.triggers == ("refactor", "cleanup")
        sibling_labels = [label for label, _ in refactor.sibling_links]
        assert sibling_labels == ["references/patterns.md", "scripts/check.sh"]

        banner = refactor.to_banner_dict()
        assert banner["env_source"] == "claude"
        assert banner["scope"] == "global"
        assert banner["kind"] == "skill"
        assert banner["triggers"] == ["refactor", "cleanup"]
        assert banner["token_estimate"] > 0

        # Reference inside skill subdir classified as reference, not skill
        assert by_rel["~/.claude/skills/refactor/references/patterns.md"].kind == "reference"

        # Cursor .mdc globs & alwaysApply
        py_rule = by_rel["~/.cursor/rules/python.mdc"]
        assert py_rule.env_source == "cursor"
        assert py_rule.kind == "rule"
        assert py_rule.globs == ("*.py", "tests/*.py")
        assert py_rule.always_apply is True

        # Standalone global files & other envs
        assert by_rel["~/.config/CLAUDE.md"].env_source == "claude"
        assert by_rel["~/.antigravity/GEMINI.md"].env_source == "gemini"
        assert by_rel["~/.config/opencode/memory/notes.md"].kind == "memory"
        assert by_rel["~/.grok/skills/search/SKILL.md"].env_source == "grok"
        assert by_rel["~/.codex/agents/scout/agent.md"].kind == "agent"
        assert by_rel["~/.agents/skills-registry.yaml"].kind == "config"

        # Project artifacts
        assert by_rel["AGENTS.md"].scope == "project"
        assert by_rel["AGENTS.md"].kind == "rule"
        assert by_rel["skills/markveil/SKILL.md"].scope == "project"
        assert by_rel["skills/markveil/SKILL.md"].env_source == "project"
        assert by_rel["prompts/audit.md"].kind == "prompt"

        # Filtering & counts
        assert len(catalog.filter(scope="project")) == 4
        assert all(a.env_source == "claude" for a in catalog.filter(env_source="claude"))
        assert all(a.kind == "skill" for a in catalog.filter(kind="skill"))
        assert len(catalog.filter(query="refactoring")) == 1
        assert len(catalog.filter(query="tests/*.py")) == 1
        assert catalog.counts_by_env()["claude"] >= 3
        assert catalog.counts_by_kind()["skill"] >= 4

    def test_security_denylist_never_scans_or_classifies_secrets_or_sessions(
        self, tmp_path, monkeypatch
    ):
        fake_home = tmp_path / "home"
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)
        monkeypatch.setenv("HOME", str(fake_home))

        secret_canary = "SUPER_SECRET_API_KEY_12345"

        # Denied directories with decoy SKILL.md / AGENTS.md files
        denied_paths = [
            _write(fake_home / ".claude" / "sessions" / "SKILL.md", secret_canary),
            _write(fake_home / ".claude" / "projects" / "p1" / "CLAUDE.md", secret_canary),
            _write(fake_home / ".codex" / "archived_sessions" / "AGENTS.md", secret_canary),
            _write(fake_home / ".gemini" / "antigravity" / "brain" / "task.md", secret_canary),
            _write(fake_home / ".gemini" / "antigravity" / "conversations" / "c.md", secret_canary),
            _write(fake_home / ".cursor" / "chats" / "chat.md", secret_canary),
            _write(fake_home / ".claude" / "skills" / "ok" / "node_modules" / "SKILL.md", secret_canary),
            _write(repo / "skills" / "cache" / "SKILL.md", secret_canary),
            _write(repo / "skills" / "worktrees" / "wt1" / "SKILL.md", secret_canary),
            # Sensitive filenames inside allowlisted dirs
            _write(fake_home / ".claude" / "skills" / "credentials.md", secret_canary),
            _write(fake_home / ".claude" / ".credentials.json", secret_canary),
            _write(fake_home / ".codex" / "auth.json", secret_canary),
            _write(fake_home / ".codex" / "skills" / "my_secret.md", secret_canary),
            _write(fake_home / ".codex" / "skills" / "access_token.md", secret_canary),
            _write(fake_home / ".gemini" / "google_accounts.json", secret_canary),
            _write(fake_home / ".codex" / "skills" / "prod.env", secret_canary),
            _write(fake_home / ".codex" / "skills" / "state.sqlite3", secret_canary),
            _write(fake_home / ".codex" / "skills" / "trace.jsonl", secret_canary),
            _write(fake_home / ".codex" / "skills" / "private.pem", secret_canary),
            _write(fake_home / ".codex" / "skills" / "signing.key", secret_canary),
        ]

        # Config file with a secret inside its body must NOT have its body read into description
        _write(fake_home / ".claude" / "settings.json", f'{{"apiKey": "{secret_canary}"}}\n')
        # Valid skill to verify scanner still works
        _write(fake_home / ".claude" / "skills" / "clean" / "SKILL.md", "# Clean Skill\n")

        catalog = agentic_env.discover_agentic_catalog(project_root=repo, force_refresh=True)
        discovered_paths = {a.path for a in catalog.artifacts}

        for p in denied_paths:
            assert str(p) not in discovered_paths
            assert agentic_env.classify_agentic_file(p, project_root=repo) is None

        for art in catalog.artifacts:
            assert secret_canary not in art.description
            assert secret_canary not in art.name

        assert any(a.name == "clean" for a in catalog.artifacts)

    def test_bounded_depth_and_async_and_caching(self, tmp_path, monkeypatch):
        fake_home = tmp_path / "home"
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)
        monkeypatch.setenv("HOME", str(fake_home))

        # Depth 6 exceeds MAX_SCAN_DEPTH=4 and must be pruned
        deep_skill = _write(
            repo / "skills" / "a" / "b" / "c" / "d" / "e" / "SKILL.md",
            "# Too Deep\n",
        )
        shallow_skill = _write(repo / "skills" / "ok" / "SKILL.md", "# Shallow\n")

        results: list[agentic_env.AgenticCatalog] = []
        done = threading.Event()
        thread = agentic_env.discover_agentic_catalog_async(
            callback=lambda cat: (results.append(cat), done.set()),
            project_root=repo,
            include_global=False,
            force_refresh=True,
        )
        assert done.wait(timeout=5)
        thread.join(timeout=5)
        assert len(results) == 1

        paths = {a.path for a in results[0].artifacts}
        assert str(shallow_skill) in paths
        assert str(deep_skill) not in paths

        # Warm cache hit returns the exact cached instance
        cached = agentic_env.discover_agentic_catalog(
            project_root=repo, include_global=False, force_refresh=False
        )
        assert cached is results[0]

    def test_real_host_scan_speed_and_safety(self):
        """Real-host verification: fast scan and zero denied/sensitive leaks."""
        repo_root = Path(__file__).resolve().parent.parent
        cold = agentic_env.discover_agentic_catalog(
            project_root=repo_root, include_global=True, force_refresh=True
        )
        warm = agentic_env.discover_agentic_catalog(
            project_root=repo_root, include_global=True, force_refresh=False
        )
        assert warm is cold
        # Project skills/markveil/SKILL.md must be discovered
        project_rels = {a.rel_path for a in cold.filter(scope="project")}
        assert "skills/markveil/SKILL.md" in project_rels

        # Safety invariant on real host output
        for art in cold.artifacts:
            assert not agentic_env.is_sensitive_filename(Path(art.path).name)
            rel_dirs = [seg.lower() for seg in Path(art.rel_path).parts[:-1]]
            assert not any(d in agentic_env.DENIED_DIRS for d in rel_dirs), (
                f"Denied dir leaked: {art.rel_path}"
            )
