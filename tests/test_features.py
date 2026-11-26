"""Comprehensive tests for mdviewer non-GUI feature modules."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import threading
import time
from unittest import mock

import pytest

from mdviewer import agent_cli, cli, clipboard, config, context_inspector, diff_engine, review_comments


# ---------------------------------------------------------------------------
# config.py tests
# ---------------------------------------------------------------------------
class TestConfig:
    def test_xdg_config_path(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        path = config.get_config_path()
        assert path == tmp_path / "xdg" / "md-viewer" / "config.json"

    def test_atomic_save_and_load_roundtrip(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        cfg = config.AppConfig(
            theme="obsidian",
            zoom_level=1.25,
            window_width=1280,
            window_height=820,
            sidebar_visible=True,
            sidebar_tab="context",
            sidebar_width=310,
            split_ratio=0.6,
            vim_navigation=False,
            allow_remote_images=True,
            custom_css_path="/tmp/custom.css",
            recent_files=["/a.md", "/b.md"],
            preferred_agent="claude",
            status_bar_visible=False,
        )
        saved_path = config.save_config(cfg)
        assert saved_path.is_file()
        # No leftover temporary files
        leftovers = [p for p in saved_path.parent.iterdir() if p.name.endswith(".tmp")]
        assert leftovers == []

        loaded = config.load_config()
        assert loaded == cfg

    def test_load_corrupt_and_invalid_fields_fall_back_safely(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text("{not valid json", encoding="utf-8")
        assert config.load_config(cfg_file) == config.AppConfig()

        cfg_file.write_text(
            json.dumps(
                {
                    "theme": "nonexistent",
                    "zoom_level": 99.0,
                    "window_width": 50,
                    "split_ratio": -5,
                    "vim_navigation": "yes",
                    "recent_files": ["/x.md", 123, "/x.md", ""],
                    "extra_unknown": True,
                }
            ),
            encoding="utf-8",
        )
        loaded = config.load_config(cfg_file)
        assert loaded.theme == "auto"
        assert loaded.zoom_level == 3.0
        assert loaded.window_width == 400
        assert loaded.split_ratio == 0.15
        assert loaded.vim_navigation is True
        assert loaded.recent_files == ["/x.md"]

    def test_add_recent_file_dedup_and_limit(self, tmp_path):
        cfg = config.AppConfig()
        for i in range(20):
            config.add_recent_file(cfg, str(tmp_path / f"doc-{i}.md"))
        assert len(cfg.recent_files) == 15
        assert cfg.recent_files[0].endswith("doc-19.md")

        # Adding an existing item moves it to front without duplicating
        target = str(tmp_path / "doc-10.md")
        config.add_recent_file(cfg, target)
        assert len(cfg.recent_files) == 15
        assert cfg.recent_files[0] == target
        assert cfg.recent_files.count(target) == 1


# ---------------------------------------------------------------------------
# context_inspector.py tests
# ---------------------------------------------------------------------------
class TestContextInspector:
    def test_token_estimation_and_sections(self):
        doc = (
            "Intro paragraph with several words here.\n\n"
            "# Overview\n\n"
            "Prose body text.\n\n"
            "```python\n"
            "# This comment is inside code, not a heading\n"
            "def greet(name: str) -> str:\n"
            "    return f'hello {name}'\n"
            "```\n\n"
            "## Details\n\n"
            "More details follow.\n"
        )
        report = context_inspector.analyze_document(doc, file_path="notes.md")
        assert report.is_skill_doc is False
        assert report.est_tokens == report.prose_tokens + report.code_tokens
        assert report.prose_tokens > 0
        assert report.code_tokens > 0
        assert report.words == len(doc.split())
        assert report.bytes_size == len(doc.encode("utf-8"))
        assert report.reading_minutes >= 1

        titles = [s.title for s in report.sections]
        assert titles == ["(Preamble)", "Overview", "Details"]
        assert "# This comment is inside code, not a heading" not in titles
        assert report.sections[1].line == 3
        assert report.sections[2].line == 13

    def test_skill_doc_checks_and_large_section_warning(self):
        # Missing front-matter in SKILL.md
        r1 = context_inspector.analyze_document("# My Skill\n\nBody.", file_path="/repo/SKILL.md")
        assert r1.is_skill_doc is True
        assert any("front-matter" in w for w in r1.warnings)

        # Missing description in SKILL.md
        r2 = context_inspector.analyze_document(
            "---\nname: helper\n---\n\n# My Skill\n\nBody.\n",
            file_path="SKILL.md",
        )
        assert r2.is_skill_doc is True
        assert r2.front_matter_keys == ["name"]
        assert any("description" in w for w in r2.warnings)

        # Valid SKILL.md with oversized section (> 2000 tokens -> > 8400 prose chars)
        big_body = "word " * 2200
        r3 = context_inspector.analyze_document(
            f"---\nname: helper\ndescription: Does helpful things\n---\n\n# Big Section\n\n{big_body}\n",
            file_path="SKILL.md",
        )
        assert r3.is_skill_doc is True
        assert r3.front_matter_keys == ["name", "description"]
        assert not any("missing" in w.lower() for w in r3.warnings)
        assert any("2000" in w for w in r3.warnings)

        # AGENTS.md and CLAUDE.md recognized without SKILL.md front-matter warning
        r4 = context_inspector.analyze_document("# Rules\n\nBe concise.\n", file_path="AGENTS.md")
        assert r4.is_skill_doc is True
        assert r4.warnings == []

        r5 = context_inspector.analyze_document("# Claude\n\nGuide.\n", file_path="CLAUDE.md")
        assert r5.is_skill_doc is True
        assert r5.warnings == []


# ---------------------------------------------------------------------------
# diff_engine.py tests
# ---------------------------------------------------------------------------
class TestDiffEngine:
    def test_compute_changed_lines(self):
        old = "line 1\nline 2\nline 3\n"
        new = "line 1\nline TWO\nline 3\nline 4\n"
        assert diff_engine.compute_changed_lines(old, new) == {2, 4}
        assert diff_engine.compute_changed_lines(old, old) == set()

    def test_diff_texts_unified_and_split_with_escaping(self):
        old = "# Heading One\n\nKeep this.\nOld value <script>alert(1)</script>.\n"
        new = "# Heading One\n\nKeep this.\nNew value <script>alert(1)</script>.\nAdded line.\n"

        unified = diff_engine.diff_texts(old, new, old_label="A", new_label="B", mode="unified")
        assert unified.error is None
        assert unified.additions == 2
        assert unified.deletions == 1
        assert unified.hunks_count == 1
        assert "diff-hunk-heading" in unified.html
        assert "# Heading One" in unified.html
        assert '<del class="diff-word">Old</del>' in unified.html
        assert '<ins class="diff-word">New</ins>' in unified.html
        assert "<script>" not in unified.html
        assert "&lt;script&gt;" in unified.html

        split = diff_engine.diff_texts(old, new, mode="split")
        assert "diff-split" in split.html
        assert '<ins class="diff-word">New</ins>' in split.html

    def test_diff_files_missing_returns_error(self, tmp_path):
        a = tmp_path / "a.md"
        a.write_text("hello\n", encoding="utf-8")
        report = diff_engine.diff_files(str(a), str(tmp_path / "missing.md"))
        assert report.error is not None

    def test_diff_git_head_real_repo(self, tmp_path):
        # Non-git directory returns clean error
        outside = tmp_path / "outside.md"
        outside.write_text("outside\n", encoding="utf-8")
        outside_report = diff_engine.diff_git_head(str(outside))
        assert outside_report.error is not None

        # Create real git repo
        repo = tmp_path / "repo"
        repo.mkdir()

        def git(*args: str) -> None:
            subprocess.run(
                ["git", "-C", str(repo), *args],
                check=True,
                capture_output=True,
                text=True,
            )

        git("init")
        git("config", "user.email", "test@example.com")
        git("config", "user.name", "Test User")

        doc = repo / "docs" / "PLAN.md"
        doc.parent.mkdir()
        doc.write_text("# Plan\n\nStep 1: alpha\n", encoding="utf-8")
        git("add", "docs/PLAN.md")
        git("commit", "-m", "initial")

        # Modify tracked file
        doc.write_text("# Plan\n\nStep 1: beta\nStep 2: gamma\n", encoding="utf-8")
        report = diff_engine.diff_git_head(str(doc))
        assert report.error is None
        assert report.additions == 2
        assert report.deletions == 1
        assert "# Plan" in report.html
        assert '<del class="diff-word">alpha</del>' in report.html
        assert '<ins class="diff-word">beta</ins>' in report.html

        # Untracked file returns clean non-crashing error
        untracked = repo / "untracked.md"
        untracked.write_text("hello\n", encoding="utf-8")
        untracked_report = diff_engine.diff_git_head(str(untracked))
        assert untracked_report.error is not None
        assert "untracked" in untracked_report.error.lower()

        # Flag-like revision rejected safely
        bad_rev = diff_engine.diff_git_head(str(doc), revision="--exec=evil")
        assert bad_rev.error is not None


# ---------------------------------------------------------------------------
# review_comments.py tests
# ---------------------------------------------------------------------------
class TestReviewComments:
    def test_session_crud_and_export(self):
        session = review_comments.ReviewSession()
        c1 = session.add("Architecture", "Line one\nLine two", "Clarify retry backoff.", line=14)
        c2 = session.add("Testing", "Run tests", "Add integration check.")
        assert len(session) == 2

        updated = session.update(c1.id, feedback="Clarify exponential backoff.")
        assert updated is not None
        assert updated.feedback == "Clarify exponential backoff."

        assert session.delete(c2.id) is True
        assert session.delete("missing-id") is False
        assert len(session) == 1

        md = review_comments.export_markdown("/tmp/PLAN.md", session.list())
        expected = (
            "# Review: PLAN.md\n\n"
            "## Architecture\n\n"
            "> Line one\n"
            "> Line two\n\n"
            "Feedback:\n"
            "Clarify exponential backoff.\n"
        )
        assert md == expected

        session.clear()
        assert session.list() == []
        assert review_comments.default_review_path("/tmp/PLAN.md") == "/tmp/PLAN.review.md"
        assert review_comments.default_review_path(None) == "untitled.review.md"


# ---------------------------------------------------------------------------
# clipboard.py tests
# ---------------------------------------------------------------------------
class TestClipboard:
    def test_html_to_markdown_elements(self):
        raw_html = """
        <html>
          <head><style>.x{color:red}</style><script>evil()</script></head>
          <body>
            <h1>Main Title</h1>
            <p>Hello <strong>bold</strong> and <em>italic</em> with <code>inline()</code>.</p>
            <p>Visit <a href="https://example.com">Example</a>.<br>Next line.</p>
            <blockquote>Quote here</blockquote>
            <ul>
              <li>First</li>
              <li>Second
                <ol>
                  <li>Sub one</li>
                  <li>Sub two</li>
                </ol>
              </li>
            </ul>
            <pre><code class="language-python">def x():\n    return 1</code></pre>
            <hr>
            <table>
              <thead><tr><th>Col A</th><th>Col B</th></tr></thead>
              <tbody><tr><td>1</td><td>2</td></tr></tbody>
            </table>
          </body>
        </html>
        """
        md = clipboard.html_to_markdown(raw_html)
        assert "# Main Title" in md
        assert "**bold**" in md
        assert "*italic*" in md
        assert "`inline()`" in md
        assert "[Example](https://example.com)" in md
        assert "> Quote here" in md
        assert "- First" in md
        assert "  1. Sub one" in md
        assert "```python\ndef x():\n    return 1\n```" in md
        assert "---" in md
        assert "| Col A | Col B |" in md
        assert "| --- | --- |" in md
        assert "| 1 | 2 |" in md
        assert "evil()" not in md
        assert "\n\n\n" not in md

    def test_read_and_write_clipboard_cli_fallback(self):
        with mock.patch.object(clipboard, "_get_gtk_clipboard", return_value=(None, None, None)):
            with mock.patch("mdviewer.clipboard.subprocess.run") as run_mock:
                run_mock.return_value = subprocess.CompletedProcess(
                    args=["wl-paste"],
                    returncode=0,
                    stdout=b"<h2>Clip</h2><p>Body</p>",
                    stderr=b"",
                )
                payload = clipboard.read_clipboard_smart(prefer_html_convert=True)
                assert payload.was_html is True
                assert "## Clip" in payload.text
                assert "Body" in payload.text

            with mock.patch("mdviewer.clipboard.subprocess.run") as run_mock:
                run_mock.return_value = subprocess.CompletedProcess(
                    args=["wl-copy"], returncode=0, stdout="", stderr=""
                )
                assert clipboard.write_clipboard_text("copied") is True


# ---------------------------------------------------------------------------
# agent_cli.py tests
# ---------------------------------------------------------------------------
class TestAgentCli:
    def test_detect_and_build_command(self):
        def fake_which(name: str) -> str | None:
            return f"/usr/bin/{name}" if name in ("claude", "agy") else None

        with mock.patch("mdviewer.agent_cli.shutil.which", side_effect=fake_which):
            agents = agent_cli.detect_available_agents()
        assert [a.id for a in agents] == ["claude", "agy"]
        assert agents[0].executable == "/usr/bin/claude"

        assert agent_cli.build_command("claude", "hi") == ["claude", "-p", "hi"]
        assert agent_cli.build_command("codex", "hi") == ["codex", "exec", "hi"]
        assert agent_cli.build_command("agy", "hi") == [
            "agy",
            "-p",
            "hi",
            "--output-format",
            "text",
        ]
        with pytest.raises(ValueError):
            agent_cli.build_command("unknown", "hi")

        assert set(agent_cli.PROMPT_PRESETS) == {"summarize", "gaps", "architecture", "tighten"}

    def test_prompt_bounding_and_async_run_and_cancel(self):
        long_doc = "A" * 500
        bounded = agent_cli.build_agent_prompt(long_doc, "spec.md", "Summarize", max_chars=100)
        assert "truncated at 100 of 500" in bounded
        assert "spec.md" in bounded

        # Run async with a real short Python subprocess via mocked build_command
        done_event = threading.Event()
        results: list[str] = []
        errors: list[str] = []
        dispatched: list[bool] = []

        def fake_dispatch(fn):
            dispatched.append(True)
            fn()

        with mock.patch(
            "mdviewer.agent_cli.build_command",
            return_value=[sys.executable, "-c", "print('agent ok')"],
        ):
            handle = agent_cli.run_agent_async(
                backend_id="claude",
                document_text="# Doc",
                file_path="doc.md",
                question="Check",
                on_done=lambda out: (results.append(out), done_event.set()),
                on_error=lambda err: (errors.append(err), done_event.set()),
                dispatch=fake_dispatch,
            )
            assert handle.wait(timeout=5)
        assert done_event.is_set()
        assert dispatched == [True]
        assert results == ["agent ok"]
        assert errors == []

        # Cancellation terminates long-running process cleanly
        cancel_done: list[str] = []
        cancel_errs: list[str] = []
        with mock.patch(
            "mdviewer.agent_cli.build_command",
            return_value=[sys.executable, "-c", "import time; time.sleep(30)"],
        ):
            handle2 = agent_cli.run_agent_async(
                backend_id="claude",
                document_text="# Doc",
                file_path=None,
                question="Check",
                on_done=cancel_done.append,
                on_error=cancel_errs.append,
            )
            time.sleep(0.1)
            handle2.cancel()
            assert handle2.wait(timeout=5)
        assert handle2.cancelled is True
        assert cancel_done == []
        assert cancel_errs == []


# ---------------------------------------------------------------------------
# cli.py tests
# ---------------------------------------------------------------------------
class TestCli:
    def test_parse_args_flags_and_stdin(self):
        opts = cli.parse_args(
            [
                "-e",
                "--watch",
                "--quick",
                "--readonly",
                "--line",
                "42",
                "--section",
                "Architecture",
                "--theme",
                "nordic",
                "README.md",
                "PLAN.md",
            ]
        )
        assert opts.mode == "edit"
        assert opts.watch is True
        assert opts.quick is True
        assert opts.readonly is True
        assert opts.line == 42
        assert opts.section == "Architecture"
        assert opts.theme == "nordic"
        assert opts.files == ["README.md", "PLAN.md"]
        assert opts.stdin_text is None

        # Explicit '-' stdin
        opts_dash = cli.parse_args(["-s", "-"], stdin_stream=io.StringIO("# From Dash\n"))
        assert opts_dash.mode == "split"
        assert opts_dash.files == []
        assert opts_dash.stdin_text == "# From Dash\n"

        # Implicit piped stdin when no files provided
        opts_piped = cli.parse_args([], stdin_stream=io.StringIO("# Piped\n"))
        assert opts_piped.stdin_text == "# Piped\n"

        # Empty piped stream (e.g. /dev/null desktop launch) does not trigger stdin buffer
        opts_empty_pipe = cli.parse_args([], stdin_stream=io.StringIO(""))
        assert opts_empty_pipe.stdin_text is None

        # Diff and git-diff options
        opts_diff = cli.parse_args(["--diff", "a.md", "b.md", "--clipboard"])
        assert opts_diff.diff_files == ("a.md", "b.md")
        assert opts_diff.clipboard is True

        opts_git = cli.parse_args(["--git-diff", "README.md"])
        assert opts_git.git_diff_file == "README.md"

        with pytest.raises(SystemExit) as exc_info:
            cli.parse_args(["--version"])
        assert exc_info.value.code == 0

    def test_main_lazy_app_launch(self, monkeypatch):
        captured: dict[str, object] = {}

        class FakeApp:
            def __init__(self, launch_options=None):
                captured["launch_options"] = launch_options

            def run(self, argv):
                captured["run_argv"] = argv
                return 0

        fake_app_mod = type(sys)("mdviewer.app")
        fake_app_mod.MarkdownViewerApp = FakeApp
        monkeypatch.setitem(sys.modules, "mdviewer.app", fake_app_mod)

        rc = cli.main(["md-viewer", "--edit", "notes.md"])
        assert rc == 0
        assert captured["run_argv"] == ["md-viewer"]
        assert isinstance(captured["launch_options"], cli.LaunchOptions)
        assert captured["launch_options"].mode == "edit"
        assert captured["launch_options"].files == ["notes.md"]
