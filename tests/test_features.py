"""Comprehensive tests for mdviewer non-GUI feature modules."""

from __future__ import annotations

import io
import json
import os
import stat
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
    def test_xdg_config_path_and_legacy_fallback(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        path = config.get_config_path()
        assert path == tmp_path / "xdg" / "markveil" / "config.json"

        legacy_path = config.get_legacy_config_path()
        assert legacy_path == tmp_path / "xdg" / "md-viewer" / "config.json"
        legacy_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_path.write_text('{"theme": "nordic", "zoom_level": 1.4}\n', encoding="utf-8")

        loaded = config.load_config()
        assert loaded.theme == "nordic"
        assert loaded.zoom_level == 1.4

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

    def test_save_config_optional_fsync(self, tmp_path):
        cfg = config.AppConfig(theme="paper")
        target = tmp_path / "config.json"

        with mock.patch("mdviewer.config.os.fsync") as fsync_mock:
            config.save_config(cfg, target)
            fsync_mock.assert_not_called()

        with mock.patch("mdviewer.config.os.fsync") as fsync_mock:
            config.save_config(cfg, target, fsync=True)
            fsync_mock.assert_called_once()

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
        assert report.agentic_artifact is None
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
        assert r1.agentic_artifact is not None
        assert r1.agentic_artifact.kind == "skill"
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

        # AGENTS.md, CLAUDE.md, and GEMINI.md recognized without SKILL.md front-matter warning
        r4 = context_inspector.analyze_document("# Rules\n\nBe concise.\n", file_path="AGENTS.md")
        assert r4.is_skill_doc is True
        assert r4.warnings == []

        r5 = context_inspector.analyze_document("# Claude\n\nGuide.\n", file_path="CLAUDE.md")
        assert r5.is_skill_doc is True
        assert r5.warnings == []

        r6 = context_inspector.analyze_document("# Gemini\n\nGuide.\n", file_path="GEMINI.md")
        assert r6.is_skill_doc is True
        assert r6.warnings == []

    def test_mdc_rule_and_agent_checks(self, tmp_path):
        mdc_path = tmp_path / ".cursor" / "rules" / "style.mdc"
        mdc_path.parent.mkdir(parents=True)
        mdc_path.write_text("# Style\nUse tabs.\n", encoding="utf-8")

        r_missing = context_inspector.analyze_document(
            mdc_path.read_text(encoding="utf-8"),
            file_path=str(mdc_path),
        )
        assert r_missing.is_skill_doc is True
        assert r_missing.agentic_artifact is not None
        assert r_missing.agentic_artifact.kind == "rule"
        assert any(".mdc" in w for w in r_missing.warnings)

        r_valid = context_inspector.analyze_document(
            "---\ndescription: Python style\nglobs: '*.py'\n---\n\n# Style\n",
            file_path=str(mdc_path),
        )
        assert r_valid.warnings == []

        agent_path = tmp_path / "agents" / "auditor" / "agent.md"
        agent_path.parent.mkdir(parents=True)
        agent_path.write_text("Plain body with no heading or frontmatter.\n", encoding="utf-8")
        r_agent = context_inspector.analyze_document(
            agent_path.read_text(encoding="utf-8"),
            file_path=str(agent_path),
        )
        assert r_agent.is_skill_doc is True
        assert r_agent.agentic_artifact is not None
        assert r_agent.agentic_artifact.kind == "agent"
        assert any("Agent definition" in w for w in r_agent.warnings)

    def test_broken_local_links_detection(self, tmp_path):
        (tmp_path / "references").mkdir()
        (tmp_path / "references" / "exists.md").write_text("# Ok\n", encoding="utf-8")
        doc_path = tmp_path / "SKILL.md"
        content = (
            "---\nname: demo\ndescription: Demo skill\n---\n\n"
            "# Demo\n\n"
            "See [Valid](references/exists.md#section) and [Broken](references/missing.md).\n"
            "Also ignore [Web](https://example.com) and [Anchor](#demo).\n"
            "Inline code `[Fake](references/nope.md)` is ignored.\n\n"
            "```markdown\n[Fenced](references/fenced-missing.md)\n```\n"
        )
        doc_path.write_text(content, encoding="utf-8")
        report = context_inspector.analyze_document(content, file_path=str(doc_path))
        assert report.broken_links == ["references/missing.md"]
        assert any("references/missing.md" in w for w in report.warnings)
        assert not any("exists.md" in w for w in report.warnings)
        assert not any("fenced-missing.md" in w for w in report.warnings)
        assert not any("nope.md" in w for w in report.warnings)


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
        assert session.has_unexported_changes is False

        c1 = session.add("Architecture", "Line one\nLine two", "Clarify retry backoff.", line=14)
        assert session.has_unexported_changes is True
        c2 = session.add("Testing", "Run tests", "Add integration check.")
        assert len(session) == 2

        session.mark_exported()
        assert session.has_unexported_changes is False

        updated = session.update(c1.id, feedback="Clarify exponential backoff.")
        assert updated is not None
        assert updated.feedback == "Clarify exponential backoff."
        assert session.has_unexported_changes is True

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
        assert session.has_unexported_changes is False
        assert review_comments.default_review_path("/tmp/PLAN.md") == "/tmp/PLAN.review.md"
        assert review_comments.default_review_path(None) == "untitled.review.md"

    def test_sidecar_discovery_and_markdown_roundtrip(self, tmp_path):
        doc = tmp_path / "SPEC.md"
        doc.write_text("# Spec\n\nBody.\n", encoding="utf-8")
        assert review_comments.find_sidecar_review_path(doc) is None

        session = review_comments.ReviewSession()
        session.add("Overview", "First line\nSecond line", "Expand problem statement.\nAdd metrics.")
        session.add("Security", "", "Confirm CSP nonce behavior.")

        sidecar = tmp_path / "SPEC.review.md"
        exported = review_comments.export_markdown(str(doc), session.list())
        sidecar.write_text(exported, encoding="utf-8")

        found = review_comments.find_sidecar_review_path(doc)
        assert found == sidecar
        # A .review.md file should not detect itself as having a sidecar
        assert review_comments.find_sidecar_review_path(sidecar) is None

        loaded = review_comments.load_review_markdown(sidecar, target_path=doc)
        assert len(loaded) == 2
        assert loaded[0].heading == "Overview"
        assert loaded[0].quote == "First line\nSecond line"
        assert loaded[0].feedback == "Expand problem statement.\nAdd metrics."
        assert loaded[1].heading == "Security"
        assert loaded[1].quote == ""
        assert loaded[1].feedback == "Confirm CSP nonce behavior."

        # Exact Markdown round-trip parity
        re_exported = review_comments.export_markdown(str(doc), loaded)
        assert re_exported == exported

        session2 = review_comments.ReviewSession()
        count = session2.load_from_sidecar(sidecar)
        assert count == 2
        assert session2.has_unexported_changes is False


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
        clipboard.get_clipboard_history().clear()
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
                # Auto-recorded in history
                latest = clipboard.get_clipboard_history().latest()
                assert latest is not None
                assert latest.source == "html"
                assert "## Clip" in latest.text

            with mock.patch("mdviewer.clipboard.subprocess.run") as run_mock:
                run_mock.return_value = subprocess.CompletedProcess(
                    args=["wl-copy"], returncode=0, stdout="", stderr=""
                )
                assert clipboard.write_clipboard_text("copied") is True
                _, kwargs = run_mock.call_args
                assert kwargs.get("stdout") is subprocess.DEVNULL
                assert kwargs.get("stderr") is subprocess.DEVNULL
                assert "capture_output" not in kwargs

    def test_write_clipboard_gtk_returns_immediately_without_cli(self):
        fake_cb = mock.MagicMock()
        # Simulate slow Wayland/XWayland clipboard manager persistence on store().
        fake_cb.store.side_effect = lambda: time.sleep(0.08)
        with (
            mock.patch.object(clipboard, "_get_gtk_clipboard", return_value=(object(), object(), fake_cb)),
            mock.patch("mdviewer.clipboard.subprocess.run") as run_mock,
        ):
            t0 = time.perf_counter()
            ok = clipboard.write_clipboard_text("hello gtk")
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
        assert ok is True
        assert elapsed_ms < 10.0, f"Interactive GTK clipboard write took {elapsed_ms:.2f}ms"
        fake_cb.set_text.assert_called_once_with("hello gtk", -1)
        fake_cb.store.assert_not_called()
        run_mock.assert_not_called()

    def test_write_clipboard_store_immediately_and_flush_clipboard(self):
        fake_cb = mock.MagicMock()
        with mock.patch.object(clipboard, "_get_gtk_clipboard", return_value=(object(), object(), fake_cb)):
            assert clipboard.write_clipboard_text("persist now", store_immediately=True) is True
            fake_cb.set_text.assert_called_once_with("persist now", -1)
            fake_cb.store.assert_called_once()

            fake_cb.store.reset_mock()
            clipboard.flush_clipboard()
            fake_cb.store.assert_called_once()

        # flush_clipboard must be safe when GTK is unavailable or store() raises.
        with mock.patch.object(clipboard, "_get_gtk_clipboard", return_value=(None, None, None)):
            clipboard.flush_clipboard()

        failing_cb = mock.MagicMock()
        failing_cb.store.side_effect = RuntimeError("display gone")
        with mock.patch.object(clipboard, "_get_gtk_clipboard", return_value=(object(), object(), failing_cb)):
            clipboard.flush_clipboard()

    def test_write_clipboard_gtk_real_latency_under_10ms(self):
        """When a live GTK display is present, interactive write_clipboard_text completes in <10ms."""
        _gtk, _gdk, cb = clipboard._get_gtk_clipboard()
        if cb is None:
            pytest.skip("No GTK display available")
        # Warm up once, then measure interactive write latency.
        assert clipboard.write_clipboard_text("markveil-latency-warmup") is True
        t0 = time.perf_counter()
        ok = clipboard.write_clipboard_text("markveil-latency-check")
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        assert ok is True
        assert elapsed_ms < 10.0, f"Live GTK write_clipboard_text took {elapsed_ms:.2f}ms (>= 10ms)"

    def test_write_clipboard_non_blocking_with_daemonized_xclip(self, tmp_path, monkeypatch):
        """Simulate xclip forking a background daemon holding open stdout/stderr descriptors."""
        fake_bin = tmp_path / "bin"
        fake_bin.mkdir()
        daemon_xclip = fake_bin / "xclip"
        daemon_xclip.write_text(
            f"#!{sys.executable}\n"
            "import subprocess, sys, time\n"
            "data = sys.stdin.read()\n"
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(5)'])\n"
            "sys.exit(0)\n",
            encoding="utf-8",
        )
        daemon_xclip.chmod(daemon_xclip.stat().st_mode | stat.S_IXUSR)

        # Put only fake_bin on PATH so wl-copy is absent and xclip resolves to our simulator
        monkeypatch.setenv("PATH", str(fake_bin))

        with mock.patch.object(clipboard, "_get_gtk_clipboard", return_value=(None, None, None)):
            t0 = time.perf_counter()
            ok = clipboard.write_clipboard_text("fast clipboard write")
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

        assert ok is True
        assert elapsed_ms < 500.0, f"write_clipboard_text blocked for {elapsed_ms:.1f}ms"

    def test_read_clipboard_prefers_markdown_plain_over_editor_html_wrapper(self):
        md_plain = "# Release Notes\n\n- Item one\n- Item two\n\n```python\nprint('hi')\n```\n"
        editor_html = (
            "<meta charset='utf-8'>"
            "<div style='font-family: monospace; color: #ddd'>"
            "<div><span style='color: #569cd6'># Release Notes</span></div>"
            "<div><span>- Item one</span></div>"
            "</div>"
        )

        class FakeSel:
            def get_data(self):
                return editor_html.encode("utf-8")

        fake_cb = mock.MagicMock()
        fake_cb.wait_for_contents.return_value = FakeSel()
        fake_cb.wait_for_text.return_value = md_plain

        fake_gdk = mock.MagicMock()
        fake_gdk.Atom.intern.return_value = "text/html"

        clipboard.get_clipboard_history().clear()
        with mock.patch.object(clipboard, "_get_gtk_clipboard", return_value=(object(), fake_gdk, fake_cb)):
            payload = clipboard.read_clipboard_smart(prefer_html_convert=True)

        assert payload.was_html is False
        assert payload.text == md_plain

    def test_clipboard_history_dedup_and_ring_buffer(self):
        history = clipboard.ClipboardHistory(max_entries=15)
        assert history.latest() is None
        assert history.record("") is None
        assert history.record("   \n\t ") is None

        for idx in range(20):
            history.record(f"Entry {idx} " + ("x" * 90), source="text")

        entries = history.entries()
        assert len(entries) == 15
        assert entries[0].text.startswith("Entry 19 ")
        assert entries[-1].text.startswith("Entry 5 ")
        assert len(entries[0].preview) <= 80
        assert entries[0].preview.endswith("…")
        assert entries[0].char_count == len(entries[0].text)

        # Recording a duplicate moves it to the top without increasing count
        dup_text = entries[-1].text
        history.record(dup_text, source="html")
        entries_after = history.entries()
        assert len(entries_after) == 15
        assert entries_after[0].text == dup_text
        assert entries_after[0].source == "html"
        assert entries_after[0].was_html is True
        assert entries_after[1].was_html is False
        assert sum(1 for e in entries_after if e.text == dup_text) == 1

        # was_html keyword argument sets source cleanly and overrides default source
        html_entry = history.record("## From HTML", was_html=True)
        assert html_entry is not None
        assert html_entry.source == "html"
        assert html_entry.was_html is True

        plain_entry = history.record("Plain override", source="html", was_html=False)
        assert plain_entry is not None
        assert plain_entry.source == "text"
        assert plain_entry.was_html is False

        history.clear()
        assert history.entries() == []
        assert history.latest() is None


# ---------------------------------------------------------------------------
# agent_cli.py tests
# ---------------------------------------------------------------------------
class TestAgentCli:
    def test_detect_and_build_command(self):
        def fake_which(name: str, path: str | None = None) -> str | None:
            return f"/usr/bin/{name}" if name in ("claude", "agy") else None

        with mock.patch("mdviewer.agent_cli.shutil.which", side_effect=fake_which):
            agents = agent_cli.detect_available_agents()
            installed = agent_cli.detect_installed_agents()
        assert agents == installed
        assert [a.id for a in agents] == ["claude", "agy"]
        assert agents[0].executable == "/usr/bin/claude"

        assert agent_cli.build_command("claude", "hi") == [
            "claude",
            "-p",
            "hi",
            "--output-format",
            "text",
        ]
        assert agent_cli.build_command("codex", "hi") == ["codex", "exec", "hi"]
        assert agent_cli.build_command("agy", "hi") == [
            "agy",
            "-p",
            "hi",
            "--output-format",
            "text",
        ]
        assert agent_cli.build_command("cursor-agent", "hi") == [
            "cursor-agent",
            "-p",
            "hi",
            "--output-format",
            "text",
        ]
        assert agent_cli.build_command("opencode", "hi") == ["opencode", "run", "hi"]
        assert agent_cli.build_command("kimi", "hi") == [
            "kimi",
            "-p",
            "hi",
            "--output-format",
            "text",
        ]
        assert agent_cli.build_command("gemini", "hi") == ["gemini", "-p", "hi"]
        assert agent_cli.build_command("cline", "hi") == ["cline", "--plan", "hi"]
        assert agent_cli.build_command("devin", "hi") == ["devin", "-p", "hi"]
        with pytest.raises(ValueError):
            agent_cli.build_command("unknown", "hi")

        assert set(agent_cli.SUPPORTED_AGENT_IDS) == {
            "claude",
            "codex",
            "agy",
            "cursor-agent",
            "opencode",
            "kimi",
            "gemini",
            "cline",
            "devin",
        }
        assert set(agent_cli.PROMPT_PRESETS) == {"summarize", "gaps", "architecture", "tighten"}

    def test_augmented_path_semver_order_and_minimal_path_discovery(self, tmp_path, monkeypatch):
        fake_home = tmp_path / "home"
        local_bin = fake_home / ".local" / "bin"
        nvm_old = fake_home / ".nvm" / "versions" / "node" / "v20.19.2" / "bin"
        nvm_new = fake_home / ".nvm" / "versions" / "node" / "v24.22.1" / "bin"
        fnm_bin = fake_home / ".fnm" / "node-versions" / "v22.5.0" / "installation" / "bin"
        opencode_bin = fake_home / ".opencode" / "bin"
        kimi_bin = fake_home / ".kimi-code" / "bin"
        sys_bin = tmp_path / "sysbin"

        for d in (local_bin, nvm_old, nvm_new, fnm_bin, opencode_bin, kimi_bin, sys_bin):
            d.mkdir(parents=True)

        def make_exe(path):
            path.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
            path.chmod(path.stat().st_mode | stat.S_IXUSR)

        make_exe(local_bin / "claude")
        make_exe(local_bin / "cursor-agent")
        make_exe(nvm_old / "codex")
        make_exe(nvm_new / "codex")
        make_exe(nvm_old / "gemini")
        make_exe(opencode_bin / "opencode")
        make_exe(kimi_bin / "kimi")
        # Decoy IDE binaries that must NEVER be matched
        make_exe(sys_bin / "cursor")
        make_exe(sys_bin / "devin-desktop")

        monkeypatch.setenv("HOME", str(fake_home))
        monkeypatch.setenv("PATH", str(sys_bin))

        aug = agent_cli.get_augmented_path()
        parts = aug.split(os.pathsep)
        assert str(nvm_new) in parts
        assert str(nvm_old) in parts
        assert parts.index(str(nvm_new)) < parts.index(str(nvm_old))
        assert str(fnm_bin) in parts
        assert str(local_bin) in parts

        detected = agent_cli.detect_installed_agents()
        by_id = {b.id: b.executable for b in detected}
        assert by_id["claude"] == str(local_bin / "claude")
        assert by_id["cursor-agent"] == str(local_bin / "cursor-agent")
        assert by_id["codex"] == str(nvm_new / "codex")  # Newest Node wins
        assert by_id["gemini"] == str(nvm_old / "gemini")
        assert by_id["opencode"] == str(opencode_bin / "opencode")
        assert by_id["kimi"] == str(kimi_bin / "kimi")
        assert "devin" not in by_id

        # If cursor-agent is absent, /usr/bin/cursor must NEVER match
        (local_bin / "cursor-agent").unlink()
        detected2 = agent_cli.detect_installed_agents()
        assert "cursor-agent" not in {b.id for b in detected2}

    def test_node_shebang_cli_runs_under_minimal_desktop_path(self, tmp_path, monkeypatch):
        """Verify #!/usr/bin/env node CLIs work when inherited PATH lacks Node."""
        fake_home = tmp_path / "home"
        nvm_bin = fake_home / ".nvm" / "versions" / "node" / "v24.22.1" / "bin"
        nvm_bin.mkdir(parents=True)

        fake_node = nvm_bin / "node"
        fake_node.write_text(
            f"#!{sys.executable}\n"
            "import sys\n"
            "print('node-shebang-ok:' + sys.argv[2])\n",
            encoding="utf-8",
        )
        fake_node.chmod(fake_node.stat().st_mode | stat.S_IXUSR)

        fake_codex = nvm_bin / "codex"
        fake_codex.write_text("#!/usr/bin/env node\nconsole.log('ignored');\n", encoding="utf-8")
        fake_codex.chmod(fake_codex.stat().st_mode | stat.S_IXUSR)

        monkeypatch.setenv("HOME", str(fake_home))
        # Minimal .desktop PATH containing /usr/bin (for /usr/bin/env) but NO node
        monkeypatch.setenv("PATH", "/usr/bin:/bin")

        done: list[str] = []
        errs: list[str] = []
        handle = agent_cli.run_agent_async(
            backend_id="codex",
            document_text="# Spec",
            file_path="spec.md",
            question="Check",
            on_done=done.append,
            on_error=errs.append,
        )
        assert handle.wait(timeout=5)
        assert errs == []
        assert done == ["node-shebang-ok:exec"]

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
