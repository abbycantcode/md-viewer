"""Unit tests for mdviewer.markdown_engine and package metadata."""

from __future__ import annotations

import json
from pathlib import Path
import re
import time

import markdown

import mdviewer
from mdviewer import client_js, diff_engine, themes
from mdviewer.markdown_engine import (
    CustomHtmlFormatter,
    HeadingItem,
    RenderResult,
    _render_json_tree_html,
    _unique_slug_fast,
    detect_file_kind,
    extract_headings,
    is_supported_local_file,
    render_document,
    render_markdown,
    toggle_task_checkbox_in_text,
)


def test_package_version() -> None:
    assert mdviewer.__version__ == "2.0.0"


def test_custom_html_formatter_escapes_data_lang() -> None:
    fmt = CustomHtmlFormatter(lang_str='language-py" onclick="alert(1)')
    out = "".join(chunk for _, chunk in fmt._wrap_div([(0, "<pre></pre>")]))
    assert 'data-lang="py&quot; onclick=&quot;alert(1)"' in out
    assert '" onclick="alert(1)"' not in out.replace("&quot;", "")


def test_soft_breaks_by_default_and_optional_hard_breaks() -> None:
    src = "Line one\nLine two"
    default_res = render_document(src)
    assert "Line one\nLine two" in default_res.html
    assert "<br" not in default_res.html.split('<div class="markdown-container">')[1]

    hard_res = render_document(src, hard_breaks=True)
    body = hard_res.html.split('<div class="markdown-container">')[1]
    assert "<br" in body


def test_strikethrough_extension() -> None:
    res = render_document("This is ~~removed **bold**~~ and ~kept~ and ~~~~.")
    assert "<del>removed <strong>bold</strong></del>" in res.html
    assert "~kept~" in res.html


def test_gfm_task_lists_nested_and_front_matter_line_numbers() -> None:
    src = (
        "---\n"
        "title: Tasks\n"
        "---\n"
        "# Checklist\n"
        "\n"
        "- [ ] First task\n"
        "    - [x] Nested **done**\n"
        "- [X] Second top task\n"
    )
    res = render_document(src)
    assert 'class="task-list-item"' in res.html
    assert re.search(
        r'<input\b(?=[^>]*type="checkbox")(?=[^>]*class="task-checkbox")'
        r'(?=[^>]*data-task-index="0")(?=[^>]*data-source-line="6")[^>]*>',
        res.html,
    )
    assert re.search(
        r'<input\b(?=[^>]*checked)(?=[^>]*data-task-index="1")'
        r'(?=[^>]*data-source-line="7")[^>]*>',
        res.html,
    )
    assert re.search(
        r'<input\b(?=[^>]*checked)(?=[^>]*data-task-index="2")'
        r'(?=[^>]*data-source-line="8")[^>]*>',
        res.html,
    )
    assert "<ul>\n<li class=\"task-list-item\">" in res.html
    assert "<strong>done</strong>" in res.html


def test_toggle_task_checkbox_in_text_preserves_fences_and_crlf() -> None:
    src = (
        "---\r\n"
        "title: Demo\r\n"
        "---\r\n"
        "```markdown\r\n"
        "- [ ] example inside fence\r\n"
        "```\r\n"
        "- [ ] real task 0\r\n"
        "  - [x] nested task 1\r\n"
    )
    # Line 5 is inside the fenced block; line_hint=5 must fall back to task_index=0 -> line 7.
    toggled_0 = toggle_task_checkbox_in_text(src, task_index=0, line_hint=7, checked=True)
    assert "- [x] real task 0\r\n" in toggled_0
    assert "- [ ] example inside fence\r\n" in toggled_0

    # Fallback by task_index when line_hint is stale/None.
    toggled_1 = toggle_task_checkbox_in_text(toggled_0, task_index=1, line_hint=None, checked=False)
    assert "  - [ ] nested task 1\r\n" in toggled_1
    assert "- [ ] example inside fence\r\n" in toggled_1


def test_bare_url_autolinks_respect_code_and_existing_links() -> None:
    src = (
        "Visit https://example.com/a_b_c. Also (see https://en.wikipedia.org/wiki/Python_(lang)).\n\n"
        "Keep `https://inside-code.example` and [https://label.example](https://target.example) "
        "and <https://angle.example> clean."
    )
    res = render_document(src)
    assert '<a href="https://example.com/a_b_c">https://example.com/a_b_c</a>.' in res.html
    assert (
        '<a href="https://en.wikipedia.org/wiki/Python_(lang)">'
        "https://en.wikipedia.org/wiki/Python_(lang)</a>"
    ) in res.html
    assert "<code>https://inside-code.example</code>" in res.html
    assert '<a href="https://target.example">https://label.example</a>' in res.html
    assert '<a href="https://angle.example">https://angle.example</a>' in res.html


def test_code_first_preprocessing_4_backticks_and_math() -> None:
    src = (
        "````markdown\n"
        "```mermaid\n"
        "graph TD; A-->B;\n"
        "```\n"
        "$$x = 1$$\n"
        "````\n\n"
        "```mermaid\n"
        "graph LR; X-->Y;\n"
        "```\n\n"
        "```math\n"
        "E = mc^2\n"
        "```\n\n"
        "Inline `$not_math$` and real _emphasis_ with $a_1 + b_2$ and \\(c_3\\) and costs $5 and $10.\n\n"
        "$$\n\\sum_{i=1}^n i\n$$\n"
    )
    res = render_document(src)
    # 4-backtick outer fence must NOT be split or extracted as Mermaid/Math.
    assert res.html.count('class="mermaid-container"') == 1
    assert 'data-source="graph LR; X--&gt;Y;"' in res.html
    assert "graph TD; A--&gt;B;" in res.html  # inside highlighted markdown fence

    # Real math extracted, inline code and currency left alone.
    assert 'class="katex-display-math" data-math="E = mc^2"' in res.html
    assert 'class="katex-display-math" data-math="\\sum_{i=1}^n i"' in res.html
    assert 'class="katex-inline-math" data-math="a_1 + b_2"' in res.html
    assert 'class="katex-inline-math" data-math="c_3"' in res.html
    assert "<code>$not_math$</code>" in res.html
    assert "$5 and $10" in res.html
    assert "<em>emphasis</em>" in res.html


def test_sanitization_before_trusted_container_restoration_and_csp_nonce() -> None:
    src = (
        "---\n"
        "title: <script>alert(1)</script>\n"
        "---\n"
        "# Doc\n\n"
        '<script>alert("xss")</script>\n'
        '<svg onload="alert(1)"><circle/></svg>\n'
        '[click](javascript:alert(1))\n'
        '![remote](https://example.com/img.png)\n\n'
        "```mermaid\n"
        "graph TD; A-->B;\n"
        "```\n"
    )
    res = render_document(src, allow_remote_images=False)
    assert isinstance(res, RenderResult)
    assert res.blocked_remote_images == 1
    assert res.file_kind == "markdown"
    assert len(res.nonce) >= 16

    # Dangerous user HTML stripped, while trusted Mermaid & front-matter SVG badges survived.
    assert 'alert("xss")' not in res.html
    assert "onload=" not in res.html
    assert "javascript:" not in res.html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in res.html
    assert 'data-blocked-src="https://example.com/img.png"' in res.html
    assert 'class="blocked-remote-img"' in res.html
    assert 'class="mermaid-container"' in res.html

    # Strict CSP & nonces on all <script> tags.
    assert f"script-src 'nonce-{res.nonce}';" in res.html
    assert "img-src 'self' file: data: blob:;" in res.html
    assert "connect-src 'none';" in res.html
    script_tags = re.findall(r"<script\b[^>]*>", res.html)
    assert script_tags, "Expected bundled/inline script tags"
    for tag in script_tags:
        assert f'nonce="{res.nonce}"' in tag


def test_csp_allows_remote_images_when_enabled() -> None:
    res = render_document("![img](https://example.com/a.png)", allow_remote_images=True)
    assert res.blocked_remote_images == 0
    assert "img-src * file: data: blob:;" in res.html
    assert 'src="https://example.com/a.png"' in res.html


def test_extract_headings_matches_toc_and_skips_fences_and_front_matter() -> None:
    src = (
        "---\n"
        "title: Guide\n"
        "---\n"
        "# Intro\n"
        "````md\n"
        "# Not A Heading\n"
        "```\n"
        "## Still Inside 4-Backtick Fence\n"
        "```\n"
        "````\n"
        "## Details & **Options**\n"
        "## Details & **Options**\n"
        "### `Code` Title\n"
    )
    headings = extract_headings(src)
    assert headings == [
        HeadingItem(level=1, text="Intro", slug="intro", line=4),
        HeadingItem(level=2, text="Details & Options", slug="details-options", line=11),
        HeadingItem(level=2, text="Details & Options", slug="details-options_1", line=12),
        HeadingItem(level=3, text="Code Title", slug="code-title", line=13),
    ]

    # Verify exact parity with python-markdown's toc extension ids.
    md = markdown.Markdown(extensions=["markdown.extensions.toc"])
    rendered = md.convert("\n".join(src.splitlines()[3:]))
    for item in headings:
        assert f'id="{item.slug}"' in rendered


def test_watch_mode_marks_changed_lines() -> None:
    src = (
        "# Alpha\n\n"
        "Unchanged paragraph.\n\n"
        "Changed paragraph content.\n\n"
        "- [ ] Task item\n\n"
        "```mermaid\n"
        "graph TD; A-->B;\n"
        "```\n"
    )
    res = render_document(src, changed_lines={1, 5, 7, 10})
    assert '<h1 id="alpha" data-changed="true">' in res.html
    assert '<p data-changed="true">Changed paragraph content.</p>' in res.html
    assert "Unchanged paragraph." in res.html
    assert '<p data-changed="true">Unchanged paragraph.</p>' not in res.html
    assert '<li class="task-list-item" data-changed="true">' in res.html
    assert '<div class="mermaid-container" data-changed="true">' in res.html


def test_detect_file_kind_and_technical_renderers() -> None:
    assert detect_file_kind("notes.md") == "markdown"
    assert detect_file_kind("doc.MDX") == "markdown"
    assert detect_file_kind("data.json") == "json"
    assert detect_file_kind("tsconfig.jsonc") == "jsonc"
    assert detect_file_kind("config.yml") == "yaml"
    assert detect_file_kind("pyproject.toml") == "toml"
    assert detect_file_kind("changes.patch") == "diff"
    assert detect_file_kind("diagram.mmd") == "mermaid"
    assert detect_file_kind("notes.txt") == "text"

    # JSON & JSONC (comments + URLs in strings + trailing commas)
    jsonc = '{\n  // comment\n  "url": "https://example.com/*keep*/",\n  /* block */\n  "items": [1, 2,],\n}'
    r_jsonc = render_document(jsonc, file_path="settings.jsonc")
    assert r_jsonc.file_kind == "jsonc"
    assert "Valid JSONC" in r_jsonc.html
    assert 'class="structured-tree json-tree"' in r_jsonc.html
    assert "https://example.com/*keep*/" in r_jsonc.html

    r_bad_json = render_document('{"broken": ', file_path="bad.json")
    assert "Invalid JSON" in r_bad_json.html

    # YAML
    r_yaml = render_document("name: md-viewer\nversion: 2\n", file_path="app.yaml")
    assert r_yaml.file_kind == "yaml"
    assert "Valid YAML" in r_yaml.html
    r_bad_yaml = render_document("a: [unclosed", file_path="bad.yml")
    assert "Invalid YAML" in r_bad_yaml.html

    # TOML
    r_toml = render_document('[project]\nname = "md-viewer"\n', file_path="pyproject.toml")
    assert r_toml.file_kind == "toml"
    assert "Valid TOML" in r_toml.html
    r_bad_toml = render_document("[invalid", file_path="bad.toml")
    assert "Invalid TOML" in r_bad_toml.html

    # Diff
    r_diff = render_document(
        "--- a/f.py\n+++ b/f.py\n@@ -1,1 +1,1 @@\n-old\n+new\n",
        file_path="fix.diff",
    )
    assert r_diff.file_kind == "diff"
    assert "diff-add" in r_diff.html
    assert "diff-del" in r_diff.html
    assert "+1" in r_diff.html and "-1" in r_diff.html

    # Standalone Mermaid
    r_mmd = render_document("sequenceDiagram\n  A->>B: Hi", file_path="flow.mermaid")
    assert r_mmd.file_kind == "mermaid"
    assert 'class="mermaid-container"' in r_mmd.html

    # Plain text
    r_txt = render_document("line 1\n<script>safe</script>", file_path="readme.txt", changed_lines={2})
    assert r_txt.file_kind == "text"
    assert "&lt;script&gt;safe&lt;/script&gt;" in r_txt.html
    assert 'data-changed="true"' in r_txt.html


def test_render_markdown_compat_and_body_html_override() -> None:
    compat_html = render_markdown("# Hello", dark=True)
    assert 'class="dark"' in compat_html
    assert "<h1" in compat_html

    wrapped = render_document(
        "",
        file_kind="diff",
        theme="obsidian",
        body_html_override='<div class="diff-report"><ins>added</ins><script>bad()</script></div>',
    )
    assert '<div class="diff-report"><ins>added</ins></div>' in wrapped.html
    assert "bad()" not in wrapped.html
    assert f"script-src 'nonce-{wrapped.nonce}';" in wrapped.html


def test_is_supported_local_file_and_source_line_anchors() -> None:
    supported = [
        "README.md",
        "SKILL.md",
        "rule.mdc",
        "default.rules",
        ".cursorrules",
        "app.py",
        "setup.sh",
        "init.bash",
        "env.zsh",
        "index.js",
        "main.ts",
        "App.tsx",
        "Card.jsx",
        "lib.rs",
        "server.go",
        "main.c",
        "types.h",
        "engine.cpp",
        "engine.hpp",
        "styles.css",
        "index.html",
        "pom.xml",
        "schema.sql",
        "script.rb",
        "Main.java",
        "App.kt",
        "View.swift",
        "init.lua",
        "app.ini",
        "setup.cfg",
        "nginx.conf",
        "Makefile",
        "Dockerfile",
        "Dockerfile.dev",
        "LICENSE",
        Path("/tmp/config.toml"),
    ]
    for sample in supported:
        assert is_supported_local_file(sample), f"Expected supported: {sample}"

    unsupported = [
        "",
        "photo.png",
        "archive.tar.gz",
        "doc.pdf",
        "module.pyc",
        "data.sqlite",
        "video.mp4",
    ]
    for sample in unsupported:
        assert not is_supported_local_file(sample), f"Expected unsupported: {sample}"

    assert detect_file_kind("rule.mdc") == "markdown"
    assert detect_file_kind(".cursorrules") == "markdown"
    assert detect_file_kind("default.rules") == "code"
    assert detect_file_kind("Makefile") == "code"
    assert detect_file_kind("Dockerfile") == "code"
    assert detect_file_kind("LICENSE") == "text"
    assert detect_file_kind("script.py") == "code"

    # Source file rendering produces Pygments highlighting + line anchors without nested highlight div.
    py_src = "def greet(name: str) -> str:\n    return f'hi {name}'\n"
    res = render_document(py_src, file_path="demo.py", changed_lines={2})
    assert res.file_kind == "code"
    assert res.html.count('class="highlight mdv-source-view language-python"') == 1
    assert '<span id="L1" data-line="1" class="mdv-code-line">' in res.html
    assert '<span id="L2" data-line="2" class="mdv-code-line" data-changed="true">' in res.html

    # Plain text also exposes line anchors for #L<n> navigation.
    txt_res = render_document("MIT License\nLine 2\n", file_path="LICENSE")
    assert txt_res.file_kind == "text"
    assert 'id="L1" data-line="1"' in txt_res.html
    assert 'id="L2" data-line="2"' in txt_res.html


def test_json_tree_caps_depth_and_node_count() -> None:
    # Deeply nested JSON (depth 60) must not raise RecursionError.
    deep: dict = {"leaf": 1}
    for _ in range(60):
        deep = {"nested": deep}
    deep_html = _render_json_tree_html(deep)
    assert "max depth reached" in deep_html

    # Large JSON array (5,000 items) caps DOM nodes cleanly with a summary.
    large_payload = json.dumps({"items": list(range(5000))})
    t0 = time.perf_counter()
    res = render_document(large_payload, file_path="huge.json")
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert res.file_kind == "json"
    assert "Valid JSON" in res.html
    assert "more items" in res.html
    assert res.html.count('class="json-leaf"') <= 2100
    assert elapsed_ms < 1000.0


def test_agentic_classification_strip_and_xss_escaping() -> None:
    # Default render (agentic_meta=None) must not emit the strip.
    plain = render_document("# Plain Doc")
    assert 'class="mdv-agentic-strip"' not in plain.html

    meta = {
        "env_source": "claude",
        "scope": "global",
        "kind": "skill",
        "name": 'review-helper <script>alert("x")</script>',
        "description": 'Validates <img src=x onerror="evil()"> artifacts',
        "triggers": ["/review", "<svg onload=alert(1)>"],
        "globs": ["**/*.md", "*.mdc"],
        "always_apply": True,
        "rel_path": "~/.claude/skills/review-helper/SKILL.md",
        "token_estimate": 1450,
        "sibling_links": [
            ("references/guide.md", "/tmp/references/guide.md"),
            ("scripts/check.py", "scripts/check.py"),
            ("evil-js", "javascript:alert(1)"),
            ("evil-data", "data:text/html,<script>1</script>"),
        ],
    }
    res = render_document("# Skill Doc\n\nBody.", file_path="/tmp/SKILL.md", agentic_meta=meta)
    assert 'class="mdv-agentic-strip"' in res.html
    assert "mdv-agentic-pill" in res.html
    assert "mdv-agentic-meta" in res.html
    assert "mdv-agentic-links" in res.html
    assert "Claude" in res.html
    assert "Skill" in res.html
    assert "Global" in res.html
    assert "Always Apply" in res.html
    assert "~1,450 tok" in res.html
    assert 'href="file:///tmp/references/guide.md"' in res.html
    assert 'href="scripts/check.py"' in res.html

    # XSS payloads must be escaped/stripped and unsafe sibling hrefs dropped.
    body_section = res.html.split('<div class="markdown-container">')[1].split("<script nonce=")[0]
    assert "<script" not in body_section
    assert "<img" not in body_section
    assert "<svg" not in body_section
    assert "javascript:" not in body_section
    assert "evil-js" not in body_section
    assert "evil-data" not in body_section
    assert "&lt;script&gt;" in body_section
    assert "&lt;img src=x onerror=" in body_section
    assert "&lt;svg onload=" in body_section


def test_client_js_helpers_and_theme_css_invariants() -> None:
    js = client_js.get_client_js(theme_id="folio")
    assert "window.__markveilScrollToLine" in js
    assert "window.__markveilScrollToHeading" in js
    assert "window.__markveilGetSelectionPayload" in js
    assert 'securityLevel: "strict"' in js
    assert "mdv-line-highlight" in js
    assert "(preamble)" in js

    for theme_id in ("folio", "paper", "obsidian", "sepia", "nordic"):
        css = themes.get_document_css(theme_id)
        for cls in (
            ".mdv-agentic-strip",
            ".mdv-agentic-pill",
            ".mdv-agentic-meta",
            ".mdv-agentic-links",
            ".mdv-code-line",
            ".mdv-line-highlight",
        ):
            assert cls in css, f"Missing {cls} in theme {theme_id}"
        assert "Bitstream Charter" in css
        assert "IBM Plex Sans" in css
        assert "JetBrains Mono" in css

    # Verify sacred theme backgrounds are untouched.
    assert themes.THEMES["folio"].bg == "#FAFAF2"
    assert themes.THEMES["paper"].bg == "#FCFCFA"
    assert themes.THEMES["obsidian"].bg == "#0E1116"
    assert themes.THEMES["sepia"].bg == "#F8F3E6"
    assert themes.THEMES["nordic"].bg == "#1A1F29"


def test_duplicate_headings_fast_slugs_match_toc_parity() -> None:
    # Direct _unique_slug_fast parity check when pre-suffixed slug collides.
    seen: set[str] = set()
    counters: dict[str, int] = {}
    assert _unique_slug_fast("topic_2", seen, counters) == "topic_2"
    assert _unique_slug_fast("topic", seen, counters) == "topic"
    assert _unique_slug_fast("topic", seen, counters) == "topic_1"
    assert _unique_slug_fast("topic", seen, counters) == "topic_3"

    src = "\n".join("## Topic\n\nBody." for _ in range(500))
    t0 = time.perf_counter()
    headings = extract_headings(src)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert len(headings) == 500
    assert headings[0].slug == "topic"
    assert headings[1].slug == "topic_1"
    assert headings[2].slug == "topic_2"
    assert headings[-1].slug == "topic_499"
    assert elapsed_ms < 100.0

    # Rendered HTML heading IDs match extracted slugs.
    res = render_document(src)
    assert 'id="topic"' in res.html
    assert 'id="topic_1"' in res.html
    assert 'id="topic_2"' in res.html
    assert 'id="topic_499"' in res.html


def test_performance_budgets_50kb_render_code_and_diff() -> None:
    prose_50k = "\n".join(
        f"## Section {i}: Architecture Overview\n\n"
        f"This section describes module {i} with **important invariants**, `symbol_{i}`, "
        f"and reference to [docs](https://example.com/doc/{i}).\n\n"
        f"Additional narrative prose explaining design tradeoffs and offline rendering.\n\n"
        f"- [ ] Check invariant {i}a\n"
        f"- [x] Verify budget {i}b\n\n"
        + (
            f"```python\ndef handler_{i}(v: int) -> int:\n    return v * {i} + 1\n```\n\n"
            if i % 4 == 0
            else ""
        )
        for i in range(145)
    )[:50_000]

    code_50k = "\n".join(
        f"### Example {i}\n\n"
        f"```\nconst v_{i} = {i} + 1;\nfunction run_{i}() {{ return v_{i} * 2; }}\n```\n\n"
        f"```python\ndef fn_{i}(a: int, b: int) -> int:\n    return a + b + {i}\n```\n\n"
        for i in range(340)
    )[:50_000]

    new_50k = prose_50k.replace("Check invariant 10a", "Check invariant 10a UPDATED") + "\n## Tail\n"

    # Warm up caches once (fonts/CSS/markdown instance).
    render_document("# Warmup")

    def best_ms(fn, runs: int = 3) -> float:
        best = float("inf")
        for _ in range(runs):
            t0 = time.perf_counter()
            fn()
            best = min(best, (time.perf_counter() - t0) * 1000.0)
        return best

    prose_ms = best_ms(lambda: render_document(prose_50k))
    code_ms = best_ms(lambda: render_document(code_50k))
    diff_ms = best_ms(lambda: diff_engine.diff_texts(prose_50k, new_50k))

    assert prose_ms < 90.0, f"50KB render too slow: {prose_ms:.1f}ms (budget < 90ms)"
    assert code_ms < 220.0, f"50KB code-heavy render too slow: {code_ms:.1f}ms (budget < 220ms)"
    assert diff_ms < 30.0, f"50KB diff too slow: {diff_ms:.1f}ms (budget < 30ms)"
