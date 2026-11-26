"""Unit tests for the allowlist HTML sanitizer."""

from __future__ import annotations

from mdviewer.sanitizer import sanitize_html


def test_preserves_safe_markdown_structure() -> None:
    raw = (
        '<h1 id="intro">Title</h1>'
        "<p>Hello <strong>world</strong>, <em>italic</em>, "
        "<del>old</del>, <ins>new</ins>, <mark>hi</mark>, "
        "H<sub>2</sub>O, x<sup>2</sup>, <kbd>Ctrl+S</kbd>.</p>"
        '<blockquote><p>Quote <a href="https://example.com" title="Ex">link</a></p></blockquote>'
        "<ul><li>One</li><li>Two</li></ul>"
        '<details open><summary>More</summary><p>Inside</p></details>'
    )
    cleaned, blocked = sanitize_html(raw)
    assert blocked == 0
    assert '<h1 id="intro">Title</h1>' in cleaned
    assert "<strong>world</strong>" in cleaned
    assert '<a href="https://example.com" title="Ex">link</a>' in cleaned
    assert "<details open><summary>More</summary><p>Inside</p></details>" in cleaned


def test_strips_dangerous_tags_and_all_inner_content() -> None:
    raw = (
        "<p>Before</p>"
        "<script>alert(document.cookie)</script>"
        "<style>body { display: none; }</style>"
        '<iframe src="https://evil.example"><p>fallback</p></iframe>'
        "<object><param name='x' value='y'>bad</object>"
        "<svg onload='alert(1)'><circle cx='10' cy='10' r='5'/><script>evil()</script></svg>"
        "<form action='/steal'><textarea>secret</textarea><select><option>1</option></select></form>"
        "<noscript><img src='https://tracker.example/p.gif'></noscript>"
        "<template><div>hidden</div></template>"
        '<meta charset="utf-8"><base href="https://evil.example"><link rel="stylesheet" href="x.css">'
        "<p>After</p>"
    )
    cleaned, blocked = sanitize_html(raw)
    assert blocked == 0
    assert "<p>Before</p>" in cleaned
    assert "<p>After</p>" in cleaned
    for forbidden in (
        "script",
        "alert(",
        "style",
        "display: none",
        "iframe",
        "fallback",
        "object",
        "svg",
        "circle",
        "evil()",
        "form",
        "textarea",
        "secret",
        "select",
        "noscript",
        "tracker.example",
        "template",
        "hidden",
        "meta",
        "base",
        "link",
    ):
        assert forbidden not in cleaned


def test_strips_event_handlers_srcdoc_formaction_and_unsafe_styles() -> None:
    raw = (
        '<div onclick="alert(1)" ONMOUSEOVER="evil()" srcdoc="<script>1</script>" '
        'formaction="https://evil.example" style="background:url(javascript:alert(1))">'
        '<button type="button" onclick="x()" formaction="y">Click</button>'
        "</div>"
        '<table><tr><th style="text-align: CENTER;">Col</th>'
        '<td style="text-align: right; color: red;">Bad</td>'
        '<td style="text-align: left">Good</td></tr></table>'
        '<p style="text-align: center">Not on p</p>'
    )
    cleaned, _ = sanitize_html(raw)
    assert "onclick" not in cleaned.lower()
    assert "onmouseover" not in cleaned.lower()
    assert "srcdoc" not in cleaned.lower()
    assert "formaction" not in cleaned.lower()
    assert "background:" not in cleaned
    assert "color: red" not in cleaned
    assert '<th style="text-align: center">Col</th>' in cleaned
    assert '<td style="text-align: left">Good</td>' in cleaned
    assert "<p>Not on p</p>" in cleaned


def test_input_only_allows_checkbox_with_task_attributes() -> None:
    raw = (
        '<input type="text" value="secret">'
        '<input type="password">'
        "<input>"
        '<input type="checkbox" class="task-checkbox" data-task-index="2" '
        'data-source-line="14" checked disabled onclick="alert(1)" name="evil">'
    )
    cleaned, _ = sanitize_html(raw)
    assert 'type="text"' not in cleaned
    assert 'type="password"' not in cleaned
    assert "secret" not in cleaned
    assert "onclick" not in cleaned
    assert "name=" not in cleaned
    assert 'type="checkbox"' in cleaned
    assert 'class="task-checkbox"' in cleaned
    assert 'data-task-index="2"' in cleaned
    assert 'data-source-line="14"' in cleaned
    assert "checked" in cleaned
    assert "disabled" in cleaned


def test_url_validation_blocks_xss_schemes_and_obfuscations() -> None:
    raw = (
        '<a href="javascript:alert(1)">js</a>'
        '<a href="  java&#x09;script:alert(1)">tab-js</a>'
        '<a href="&#x6a;avascript:alert(1)">entity-js</a>'
        '<a href="vbscript:msgbox(1)">vbs</a>'
        '<a href="data:text/html,<script>alert(1)</script>">data-html</a>'
        '<a href="data:image/svg+xml,<svg onload=alert(1)>">data-svg</a>'
        '<a href="#heading-1">local-anchor</a>'
        '<a href="mailto:user@example.com">mail</a>'
        '<img src="javascript:alert(1)" alt="bad1">'
        '<img src="data:image/svg+xml;base64,PHN2Zz4=" alt="bad2">'
        '<img src="data:text/html,hi" alt="bad3">'
    )
    cleaned, blocked = sanitize_html(raw)
    assert blocked == 0
    assert "javascript:" not in cleaned.lower()
    assert "vbscript:" not in cleaned.lower()
    assert "data:text/html" not in cleaned.lower()
    assert "data:image/svg+xml" not in cleaned.lower()
    assert '<a href="#heading-1">local-anchor</a>' in cleaned
    assert '<a href="mailto:user@example.com">mail</a>' in cleaned
    assert 'alt="bad1"' in cleaned
    assert "src=" not in cleaned


def test_image_src_allowlist_and_remote_blocking() -> None:
    raw = (
        '<img src="images/diagram.png" alt="rel">'
        '<img src="file:///tmp/photo.jpg" alt="local">'
        '<img src="blob:https://app.local/123" alt="blob">'
        '<img src="data:image/png;base64,iVBORw0KGgo=" alt="raster">'
        '<img class="hero" src="https://cdn.example.com/pic.png" alt="remote1">'
        '<img src="http://example.org/a.gif" alt="remote2">'
        '<img src="//example.org/proto.png" alt="proto">'
    )
    cleaned_blocked, count_blocked = sanitize_html(raw, allow_remote_images=False)
    assert count_blocked == 3
    assert 'src="images/diagram.png"' in cleaned_blocked
    assert 'src="file:///tmp/photo.jpg"' in cleaned_blocked
    assert 'src="blob:https://app.local/123"' in cleaned_blocked
    assert 'src="data:image/png;base64,iVBORw0KGgo="' in cleaned_blocked
    assert 'data-blocked-src="https://cdn.example.com/pic.png"' in cleaned_blocked
    assert 'class="hero blocked-remote-img"' in cleaned_blocked
    assert 'data-blocked-src="http://example.org/a.gif"' in cleaned_blocked
    assert 'data-blocked-src="//example.org/proto.png"' in cleaned_blocked
    assert ' src="https://cdn.example.com' not in cleaned_blocked

    cleaned_allowed, count_allowed = sanitize_html(raw, allow_remote_images=True)
    assert count_allowed == 0
    assert 'src="https://cdn.example.com/pic.png"' in cleaned_allowed
    assert "data-blocked-src" not in cleaned_allowed


def test_preserves_code_and_pre_escaped_text_verbatim() -> None:
    raw = (
        "<pre><code>&lt;script&gt;alert('xss')&lt;/script&gt;\n"
        '&lt;img src=x onerror="alert(1)"&gt;</code></pre>'
        "<p>Inline <code>&lt;svg onload=alert(1)&gt;</code> here.</p>"
    )
    cleaned, _ = sanitize_html(raw)
    assert "&lt;script&gt;alert('xss')&lt;/script&gt;" in cleaned
    assert '&lt;img src=x onerror="alert(1)"&gt;' in cleaned
    assert "<code>&lt;svg onload=alert(1)&gt;</code>" in cleaned
    assert "<script>" not in cleaned
    assert "<svg" not in cleaned


def test_strips_comments_and_unknown_tags() -> None:
    raw = "<!-- secret comment --><marquee>Scroll</marquee><p>Safe</p>"
    cleaned, _ = sanitize_html(raw)
    assert "secret comment" not in cleaned
    assert "<marquee>" not in cleaned
    assert "Scroll<p>Safe</p>" == cleaned


def test_img_src_normalizes_backslashes() -> None:
    raw = (
        r'<img src="\\evil.com/track.png" alt="unc">'
        r'<img src="/\evil.com/slash.png" alt="mixed1">'
        r'<img src="\/evil.com/slash2.png" alt="mixed2">'
        r'<img src="https:\\evil.com\pic.png" alt="scheme-bs">'
        r'<img src="\local\img.png" alt="local-abs">'
        r'<img src="assets\diagram.png" alt="local-rel">'
        r'<img src="data:image/png;base64,iVBOR\w0KGgo=" alt="bad-data">'
    )
    cleaned_blocked, blocked = sanitize_html(raw, allow_remote_images=False)
    assert blocked == 4
    assert 'data-blocked-src="//evil.com/track.png"' in cleaned_blocked
    assert 'data-blocked-src="//evil.com/slash.png"' in cleaned_blocked
    assert 'data-blocked-src="//evil.com/slash2.png"' in cleaned_blocked
    assert 'data-blocked-src="https://evil.com/pic.png"' in cleaned_blocked
    assert 'src="/local/img.png"' in cleaned_blocked
    assert 'src="assets/diagram.png"' in cleaned_blocked
    assert "iVBOR" not in cleaned_blocked

    cleaned_allowed, allowed_blocked = sanitize_html(raw, allow_remote_images=True)
    assert allowed_blocked == 0
    assert 'src="//evil.com/track.png"' in cleaned_allowed
    assert 'src="https://evil.com/pic.png"' in cleaned_allowed


def test_allows_agentic_strip_and_source_line_attributes() -> None:
    raw = (
        '<section class="mdv-agentic-strip" aria-label="Agentic artifact classification">'
        '<span class="mdv-agentic-pill" onclick="alert(1)">Claude</span>'
        '<a class="mdv-agentic-link" href="file:///tmp/ref.md">ref.md</a>'
        '<a class="mdv-agentic-link" href="javascript:alert(1)">bad</a>'
        "</section>"
        '<div class="highlight mdv-source-view" data-lang="python">'
        '<pre><span id="L42" data-line="42" class="mdv-code-line" onmouseover="x()">x = 1</span></pre>'
        "</div>"
    )
    cleaned, blocked = sanitize_html(raw)
    assert blocked == 0
    assert '<section class="mdv-agentic-strip" aria-label="Agentic artifact classification">' in cleaned
    assert '<span class="mdv-agentic-pill">Claude</span>' in cleaned
    assert '<a class="mdv-agentic-link" href="file:///tmp/ref.md">ref.md</a>' in cleaned
    assert 'id="L42"' in cleaned
    assert 'data-line="42"' in cleaned
    assert 'class="mdv-code-line"' in cleaned
    assert "onclick" not in cleaned.lower()
    assert "onmouseover" not in cleaned.lower()
    assert "javascript:" not in cleaned.lower()
