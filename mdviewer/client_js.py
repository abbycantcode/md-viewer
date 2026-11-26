"""Client-side JavaScript generator for the WebKit2 document view in Markveil.

Provides offline KaTeX math rendering, strict-security Mermaid rendering with zoom/SVG
copy controls, code-block copy headers, heading anchor links, interactive task
checkboxes, throttled scroll/heading sync, selection review-comment pill, Vim
navigation, and deterministic scroll/section/watch-follow restoration.
"""

from __future__ import annotations

import json

from mdviewer.themes import get_mermaid_theme_vars, is_dark_theme, resolve_theme_id


def _js_json(value: object) -> str:
    """Serialize a Python value as script-safe JSON (escaping </ sequences)."""
    return json.dumps(value, ensure_ascii=True).replace("</", "<\\/")


def get_client_js(
    vim_enabled: bool = True,
    initial_scroll_ratio: float = 0.0,
    initial_section: str | None = None,
    follow_changed: bool = False,
    theme_id: str = "paper",
) -> str:
    """Return the inline client-side JS bundle configured for the active view."""
    resolved_theme = resolve_theme_id(theme_id)
    clamped_ratio = max(0.0, min(1.0, float(initial_scroll_ratio or 0.0)))
    mermaid_vars = get_mermaid_theme_vars(resolved_theme)
    dark_flag = is_dark_theme(resolved_theme)

    config_json = _js_json(
        {
            "vimEnabled": bool(vim_enabled),
            "initialScrollRatio": clamped_ratio,
            "initialSection": initial_section or "",
            "followChanged": bool(follow_changed),
            "themeId": resolved_theme,
            "isDark": dark_flag,
            "mermaidThemeVariables": mermaid_vars,
        }
    )

    return f"""\
(function() {{
    "use strict";

    var CONFIG = {config_json};
    var userScrolled = false;
    var restoredInitialView = false;

    function postToGtk(payload) {{
        try {{
            if (
                window.webkit &&
                window.webkit.messageHandlers &&
                window.webkit.messageHandlers.mdv &&
                typeof window.webkit.messageHandlers.mdv.postMessage === "function"
            ) {{
                window.webkit.messageHandlers.mdv.postMessage(JSON.stringify(payload));
                return true;
            }}
        }} catch (err) {{
            console.error("mdv bridge error:", err);
        }}
        return false;
    }}

    function escapeHtml(str) {{
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }}

    function prefersReducedMotion() {{
        return Boolean(
            window.matchMedia &&
            window.matchMedia("(prefers-reduced-motion: reduce)").matches
        );
    }}

    function scrollBehavior() {{
        return prefersReducedMotion() ? "auto" : "smooth";
    }}

    function fallbackCopy(text) {{
        var ta = document.createElement("textarea");
        ta.value = text;
        ta.setAttribute("readonly", "readonly");
        ta.style.position = "fixed";
        ta.style.left = "-9999px";
        ta.style.top = "0";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        try {{
            document.execCommand("copy");
        }} catch (_e) {{}}
        document.body.removeChild(ta);
    }}

    function copyText(text, onDone) {{
        if (postToGtk({{ type: "copy-text", text: text }})) {{
            if (onDone) onDone();
            return;
        }}
        if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {{
            navigator.clipboard.writeText(text).then(
                function() {{
                    if (onDone) onDone();
                }},
                function() {{
                    fallbackCopy(text);
                    if (onDone) onDone();
                }}
            );
        }} else {{
            fallbackCopy(text);
            if (onDone) onDone();
        }}
    }}

    function cleanHeadingText(headingEl) {{
        if (!headingEl) return "";
        var clone = headingEl.cloneNode(true);
        clone.querySelectorAll(".heading-anchor").forEach(function(btn) {{
            btn.remove();
        }});
        return (clone.textContent || "").replace(/\\s+/g, " ").trim();
    }}

    function slugifyText(text) {{
        return String(text || "")
            .toLowerCase()
            .trim()
            .replace(/[^a-z0-9\\s_-]/g, "")
            .replace(/\\s+/g, "-");
    }}

    function getDocumentHeadings() {{
        var root = document.querySelector(".markdown-container") || document.body;
        var list = root.querySelectorAll("h1, h2, h3, h4, h5, h6");
        var out = [];
        list.forEach(function(el) {{
            if (el.closest(".front-matter-card, .mermaid-error, .diff-container")) {{
                return;
            }}
            out.push(el);
        }});
        return out;
    }}

    /* ---------------------------------------------------------------------
     * 1. KaTeX Rendering
     * ------------------------------------------------------------------- */
    function renderMath() {{
        if (window.katex && typeof window.katex.render === "function") {{
            document.querySelectorAll(".katex-display-math:not(.rendered)").forEach(function(el) {{
                var tex = el.getAttribute("data-math") || el.textContent || "";
                tex = tex.replace(/^\\$\\$|\\$\\$$/g, "").trim();
                try {{
                    window.katex.render(tex, el, {{ displayMode: true, throwOnError: false }});
                    el.classList.add("rendered");
                }} catch (_e) {{}}
            }});
            document.querySelectorAll(".katex-inline-math:not(.rendered)").forEach(function(el) {{
                var tex = el.getAttribute("data-math") || el.textContent || "";
                tex = tex.replace(/^\\$|\\$$/g, "").trim();
                try {{
                    window.katex.render(tex, el, {{ displayMode: false, throwOnError: false }});
                    el.classList.add("rendered");
                }} catch (_e) {{}}
            }});
        }}
        if (typeof window.renderMathInElement === "function") {{
            try {{
                window.renderMathInElement(document.body, {{
                    delimiters: [
                        {{ left: "$$", right: "$$", display: true }},
                        {{ left: "\\\\[", right: "\\\\]", display: true }},
                        {{ left: "$", right: "$", display: false }},
                        {{ left: "\\\\(", right: "\\\\)", display: false }}
                    ],
                    throwOnError: false,
                    ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code"],
                    ignoredClasses: [
                        "katex",
                        "katex-block",
                        "katex-display-math",
                        "katex-inline-math",
                        "mermaid",
                        "mermaid-container",
                        "diff-container",
                        "json-tree"
                    ]
                }});
            }} catch (err) {{
                console.error("KaTeX auto-render error:", err);
            }}
        }}
    }}

    /* ---------------------------------------------------------------------
     * 2. Mermaid Rendering (securityLevel: "strict") + Hover Zoom Toolbar
     * ------------------------------------------------------------------- */
    function renderMermaidError(el, code, err) {{
        el.classList.add("has-error");
        var msg = (err && err.message) ? err.message : String(err);
        document.querySelectorAll('svg[id^="dmermaid"], [id^="dmermaid"]').forEach(function(r) {{
            r.remove();
        }});
        el.innerHTML =
            '<div class="mermaid-error">' +
            '<div class="mermaid-error-header">Diagram Syntax Error</div>' +
            '<div class="mermaid-error-msg">' + escapeHtml(msg) + '</div>' +
            '<details class="mermaid-error-details"><summary>Diagram Source</summary>' +
            '<pre class="mermaid-error-code">' + escapeHtml(code) + '</pre></details>' +
            '</div>';
    }}

    function attachMermaidToolbar(el) {{
        var container = el.closest(".mermaid-container");
        if (!container || container.querySelector(".mermaid-toolbar")) return;

        var header = container.querySelector(".mermaid-header");
        if (!header) {{
            header = document.createElement("div");
            header.className = "mermaid-header";
            var badge = document.createElement("span");
            badge.className = "mermaid-badge";
            badge.textContent = "Mermaid";
            header.appendChild(badge);
            container.insertBefore(header, container.firstChild);
        }}

        var toolbar = document.createElement("div");
        toolbar.className = "mermaid-toolbar";
        toolbar.setAttribute("role", "toolbar");
        toolbar.setAttribute("aria-label", "Diagram controls");

        var scale = 1.0;

        function applyScale(nextScale) {{
            scale = Math.max(0.5, Math.min(2.5, Math.round(nextScale * 100) / 100));
            resetBtn.textContent = Math.round(scale * 100) + "%";
            var svg = el.querySelector("svg");
            if (!svg) return;
            if (!svg.dataset.baseWidth) {{
                var rect = svg.getBoundingClientRect();
                var attrW = parseFloat(svg.getAttribute("width") || "0");
                var baseW = (rect && rect.width > 10) ? rect.width : (attrW > 10 ? attrW : 600);
                svg.dataset.baseWidth = String(baseW);
            }}
            var base = parseFloat(svg.dataset.baseWidth);
            if (scale === 1.0) {{
                svg.style.width = "";
                svg.style.maxWidth = "100%";
            }} else {{
                svg.style.maxWidth = "none";
                svg.style.width = Math.round(base * scale) + "px";
            }}
        }}

        var zoomOutBtn = document.createElement("button");
        zoomOutBtn.type = "button";
        zoomOutBtn.className = "mermaid-toolbar-btn";
        zoomOutBtn.textContent = "-";
        zoomOutBtn.title = "Zoom out diagram";
        zoomOutBtn.setAttribute("aria-label", "Zoom out diagram");
        zoomOutBtn.addEventListener("click", function() {{ applyScale(scale - 0.15); }});

        var resetBtn = document.createElement("button");
        resetBtn.type = "button";
        resetBtn.className = "mermaid-toolbar-btn";
        resetBtn.textContent = "100%";
        resetBtn.title = "Reset diagram zoom";
        resetBtn.setAttribute("aria-label", "Reset diagram zoom");
        resetBtn.addEventListener("click", function() {{ applyScale(1.0); }});

        var zoomInBtn = document.createElement("button");
        zoomInBtn.type = "button";
        zoomInBtn.className = "mermaid-toolbar-btn";
        zoomInBtn.textContent = "+";
        zoomInBtn.title = "Zoom in diagram";
        zoomInBtn.setAttribute("aria-label", "Zoom in diagram");
        zoomInBtn.addEventListener("click", function() {{ applyScale(scale + 0.15); }});

        var copySvgBtn = document.createElement("button");
        copySvgBtn.type = "button";
        copySvgBtn.className = "mermaid-toolbar-btn";
        copySvgBtn.textContent = "Copy SVG";
        copySvgBtn.title = "Copy diagram SVG markup";
        copySvgBtn.setAttribute("aria-label", "Copy diagram SVG markup");
        copySvgBtn.addEventListener("click", function() {{
            var svg = el.querySelector("svg");
            if (!svg) return;
            var serializer = new XMLSerializer();
            var svgMarkup = serializer.serializeToString(svg);
            copyText(svgMarkup, function() {{
                copySvgBtn.classList.add("copied");
                copySvgBtn.textContent = "Copied";
                setTimeout(function() {{
                    copySvgBtn.classList.remove("copied");
                    copySvgBtn.textContent = "Copy SVG";
                }}, 1500);
            }});
        }});

        toolbar.appendChild(zoomOutBtn);
        toolbar.appendChild(resetBtn);
        toolbar.appendChild(zoomInBtn);
        toolbar.appendChild(copySvgBtn);
        header.appendChild(toolbar);
    }}

    function renderMermaidDiagrams() {{
        if (!window.mermaid || typeof window.mermaid.initialize !== "function") {{
            return Promise.resolve();
        }}
        window.mermaid.initialize({{
            startOnLoad: false,
            theme: "base",
            securityLevel: "strict",
            fontFamily: CONFIG.mermaidThemeVariables.fontFamily,
            themeVariables: CONFIG.mermaidThemeVariables
        }});

        var items = document.querySelectorAll(".mermaid:not(.rendered)");
        var tasks = [];
        items.forEach(function(el, idx) {{
            var rawCode = el.getAttribute("data-source") || el.textContent.trim();
            var id = "mermaid-chart-" + Date.now() + "-" + idx;
            try {{
                var p = Promise.resolve(window.mermaid.render(id, rawCode))
                    .then(function(res) {{
                        el.innerHTML = res.svg;
                        el.classList.add("rendered");
                        attachMermaidToolbar(el);
                    }})
                    .catch(function(err) {{
                        console.error("Mermaid render error:", err);
                        renderMermaidError(el, rawCode, err);
                    }});
                tasks.push(p);
            }} catch (syncErr) {{
                console.error("Mermaid sync error:", syncErr);
                renderMermaidError(el, rawCode, syncErr);
            }}
        }});
        return Promise.all(tasks);
    }}

    /* ---------------------------------------------------------------------
     * 3. Code Block Headers & Copy Button
     * ------------------------------------------------------------------- */
    function formatLangName(lang) {{
        if (!lang || lang === "code" || lang === "text" || lang === "plain") return "CODE";
        var map = {{
            "js": "JavaScript", "javascript": "JavaScript",
            "ts": "TypeScript", "typescript": "TypeScript",
            "tsx": "TSX", "jsx": "JSX",
            "py": "Python", "python": "Python",
            "rb": "Ruby", "ruby": "Ruby",
            "sh": "Bash", "bash": "Bash", "zsh": "Zsh", "shell": "Shell",
            "cpp": "C++", "c++": "C++", "c": "C",
            "cs": "C#", "csharp": "C#",
            "rs": "Rust", "rust": "Rust",
            "go": "Go", "golang": "Go",
            "html": "HTML", "css": "CSS", "scss": "SCSS",
            "json": "JSON", "jsonc": "JSONC",
            "yaml": "YAML", "yml": "YAML", "toml": "TOML",
            "md": "Markdown", "markdown": "Markdown",
            "sql": "SQL", "xml": "XML", "diff": "Diff", "patch": "Patch",
            "dockerfile": "Dockerfile", "docker": "Docker"
        }};
        var lower = lang.toLowerCase();
        return map[lower] || lang.toUpperCase();
    }}

    function setupCodeBlocks() {{
        document.querySelectorAll("div.highlight").forEach(function(block) {{
            if (block.querySelector(".code-header")) return;
            var pre = block.querySelector("pre");
            if (!pre) return;

            var code = pre.querySelector("code");
            var lang = block.getAttribute("data-lang") || "";
            if (!lang && code && code.className) {{
                var m = code.className.match(/(?:language-|lang-)([\\w+-]+)/);
                if (m) lang = m[1];
            }}
            if (!lang) {{
                var m2 = block.className.match(/(?:language-|highlight-)([\\w+-]+)/);
                if (m2) lang = m2[1];
            }}

            var header = document.createElement("div");
            header.className = "code-header";

            var badge = document.createElement("span");
            badge.className = "code-lang";
            badge.textContent = formatLangName(lang);
            header.appendChild(badge);

            var btn = document.createElement("button");
            btn.type = "button";
            btn.className = "code-copy-btn";
            btn.title = "Copy code to clipboard";
            btn.setAttribute("aria-label", "Copy code to clipboard");
            btn.textContent = "Copy";

            btn.addEventListener("click", function(e) {{
                e.preventDefault();
                var text = (code ? code.innerText : pre.innerText) || "";
                copyText(text, function() {{
                    btn.classList.add("copied");
                    btn.textContent = "Copied";
                    setTimeout(function() {{
                        btn.classList.remove("copied");
                        btn.textContent = "Copy";
                    }}, 1500);
                }});
            }});

            header.appendChild(btn);
            block.insertBefore(header, pre);
        }});
    }}

    /* ---------------------------------------------------------------------
     * 4. Heading # Anchor Copy Buttons
     * ------------------------------------------------------------------- */
    function setupHeadingAnchors() {{
        getDocumentHeadings().forEach(function(heading) {{
            if (heading.querySelector(".heading-anchor")) return;
            var text = cleanHeadingText(heading);
            var slug = heading.id || slugifyText(text);
            if (!heading.id && slug) {{
                heading.id = slug;
            }}

            var btn = document.createElement("button");
            btn.type = "button";
            btn.className = "heading-anchor";
            btn.title = "Copy heading reference";
            btn.setAttribute("aria-label", "Copy heading reference for " + text);
            btn.textContent = "#";

            btn.addEventListener("click", function(e) {{
                e.preventDefault();
                e.stopPropagation();
                var posted = postToGtk({{
                    type: "copy-heading",
                    slug: slug,
                    text: text
                }});
                if (!posted) {{
                    copyText("#" + slug);
                }}
                btn.classList.add("copied");
                setTimeout(function() {{
                    btn.classList.remove("copied");
                }}, 1200);
            }});

            heading.appendChild(btn);
        }});
    }}

    /* ---------------------------------------------------------------------
     * 5. Interactive Task Checkboxes
     * ------------------------------------------------------------------- */
    function setupTaskCheckboxes() {{
        document.querySelectorAll(".task-checkbox").forEach(function(cb, fallbackIdx) {{
            if (cb.dataset.mdvBound === "1") return;
            cb.dataset.mdvBound = "1";
            cb.addEventListener("click", function() {{
                if (cb.disabled) return;
                var rawIndex = cb.getAttribute("data-task-index");
                var rawLine = cb.getAttribute("data-source-line");
                var parsedIndex = rawIndex !== null ? parseInt(rawIndex, 10) : fallbackIdx;
                var parsedLine = rawLine !== null ? parseInt(rawLine, 10) : null;
                postToGtk({{
                    type: "checkbox-toggle",
                    index: isNaN(parsedIndex) ? fallbackIdx : parsedIndex,
                    line: (parsedLine !== null && !isNaN(parsedLine)) ? parsedLine : null,
                    checked: Boolean(cb.checked)
                }});
            }});
        }});
    }}

    /* ---------------------------------------------------------------------
     * 6. Throttled Scroll & Active-Heading Tracker (~120ms)
     * ------------------------------------------------------------------- */
    function computeActiveSlug() {{
        var headings = getDocumentHeadings();
        var active = "";
        for (var i = 0; i < headings.length; i++) {{
            var rect = headings[i].getBoundingClientRect();
            if (rect.top <= 96) {{
                active = headings[i].id || slugifyText(cleanHeadingText(headings[i]));
            }} else {{
                break;
            }}
        }}
        if (!active && headings.length > 0) {{
            active = headings[0].id || slugifyText(cleanHeadingText(headings[0]));
        }}
        return active;
    }}

    function emitScrollUpdate() {{
        var scrollY = Math.round(window.scrollY || document.documentElement.scrollTop || 0);
        var maxScroll = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
        var ratio = maxScroll > 0 ? Math.max(0, Math.min(1, scrollY / maxScroll)) : 0;
        postToGtk({{
            type: "scroll-update",
            ratio: Math.round(ratio * 10000) / 10000,
            scrollY: scrollY,
            activeSlug: computeActiveSlug()
        }});
    }}

    function setupScrollTracker() {{
        var lastSent = 0;
        var pendingTimer = null;
        var THROTTLE_MS = 120;

        function schedule() {{
            var now = Date.now();
            var remaining = THROTTLE_MS - (now - lastSent);
            if (remaining <= 0) {{
                if (pendingTimer) {{
                    clearTimeout(pendingTimer);
                    pendingTimer = null;
                }}
                lastSent = now;
                emitScrollUpdate();
            }} else if (!pendingTimer) {{
                pendingTimer = setTimeout(function() {{
                    pendingTimer = null;
                    lastSent = Date.now();
                    emitScrollUpdate();
                }}, remaining);
            }}
        }}

        window.addEventListener("scroll", function() {{
            if (restoredInitialView) {{
                userScrolled = true;
            }}
            schedule();
        }}, {{ passive: true }});
    }}

    /* ---------------------------------------------------------------------
     * 7. Selection Review Comment Pill
     * ------------------------------------------------------------------- */
    function findNearestHeadingForNode(node) {{
        var headings = getDocumentHeadings();
        if (!headings.length || !node) return "";
        var target = node.nodeType === 3 ? node.parentElement : node;
        if (!target) return "";
        var nearest = "";
        for (var i = 0; i < headings.length; i++) {{
            var h = headings[i];
            if (h === target || h.contains(target)) {{
                return cleanHeadingText(h);
            }}
            var pos = h.compareDocumentPosition(target);
            if (pos & Node.DOCUMENT_POSITION_FOLLOWING) {{
                nearest = cleanHeadingText(h);
            }} else {{
                break;
            }}
        }}
        return nearest;
    }}

    function setupSelectionCommentPill() {{
        var container = document.querySelector(".markdown-container");
        if (!container) return;

        var pill = document.createElement("button");
        pill.type = "button";
        pill.className = "mdv-comment-pill";
        pill.textContent = "Add comment";
        pill.setAttribute("aria-label", "Add review comment for selected text");
        document.body.appendChild(pill);

        var currentQuote = "";
        var currentHeading = "";

        function hidePill() {{
            pill.style.display = "none";
            currentQuote = "";
            currentHeading = "";
        }}

        function updatePill() {{
            var sel = window.getSelection();
            if (!sel || sel.isCollapsed || sel.rangeCount === 0) {{
                hidePill();
                return;
            }}
            var quote = sel.toString().trim();
            if (!quote) {{
                hidePill();
                return;
            }}
            var range = sel.getRangeAt(0);
            var ancestor = range.commonAncestorContainer;
            var ancestorEl = ancestor.nodeType === 3 ? ancestor.parentElement : ancestor;
            if (!ancestorEl || !container.contains(ancestorEl)) {{
                hidePill();
                return;
            }}

            var rect = range.getBoundingClientRect();
            if (!rect || (rect.width === 0 && rect.height === 0)) {{
                hidePill();
                return;
            }}

            currentQuote = quote;
            currentHeading = findNearestHeadingForNode(range.startContainer);

            pill.style.display = "inline-flex";
            var pillRect = pill.getBoundingClientRect();
            var top = rect.top - pillRect.height - 8;
            if (top < 8) {{
                top = rect.bottom + 8;
            }}
            var left = rect.left + (rect.width / 2) - (pillRect.width / 2);
            left = Math.max(8, Math.min(window.innerWidth - pillRect.width - 8, left));
            pill.style.top = Math.round(top) + "px";
            pill.style.left = Math.round(left) + "px";
        }}

        pill.addEventListener("mousedown", function(e) {{
            e.preventDefault();
            e.stopPropagation();
        }});

        pill.addEventListener("click", function(e) {{
            e.preventDefault();
            e.stopPropagation();
            if (!currentQuote) {{
                hidePill();
                return;
            }}
            postToGtk({{
                type: "add-comment",
                heading: currentHeading,
                quote: currentQuote
            }});
            var sel = window.getSelection();
            if (sel) sel.removeAllRanges();
            hidePill();
        }});

        var selTimer = null;
        document.addEventListener("selectionchange", function() {{
            if (selTimer) clearTimeout(selTimer);
            selTimer = setTimeout(updatePill, 40);
        }});
        document.addEventListener("mouseup", function() {{
            setTimeout(updatePill, 10);
        }});
        window.addEventListener("scroll", hidePill, {{ passive: true }});
        window.addEventListener("resize", hidePill, {{ passive: true }});
        document.addEventListener("keydown", function(e) {{
            if (e.key === "Escape") hidePill();
        }});
    }}

    /* ---------------------------------------------------------------------
     * 8. Vim Navigation (j/k, d/u, gg/G, /, [/])
     * ------------------------------------------------------------------- */
    function isEditableTarget(el) {{
        if (!el) return false;
        var tag = (el.tagName || "").toUpperCase();
        if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
        return Boolean(el.isContentEditable);
    }}

    function jumpHeading(direction) {{
        var headings = getDocumentHeadings();
        if (!headings.length) return;
        var i;
        if (direction > 0) {{
            for (i = 0; i < headings.length; i++) {{
                if (headings[i].getBoundingClientRect().top > 24) {{
                    headings[i].scrollIntoView({{ behavior: scrollBehavior(), block: "start" }});
                    return;
                }}
            }}
        }} else {{
            for (i = headings.length - 1; i >= 0; i--) {{
                if (headings[i].getBoundingClientRect().top < -12) {{
                    headings[i].scrollIntoView({{ behavior: scrollBehavior(), block: "start" }});
                    return;
                }}
            }}
            window.scrollTo({{ top: 0, behavior: scrollBehavior() }});
        }}
    }}

    function setupVimNavigation() {{
        if (!CONFIG.vimEnabled) return;
        var pendingG = false;
        var gTimer = null;

        function clearG() {{
            pendingG = false;
            if (gTimer) {{
                clearTimeout(gTimer);
                gTimer = null;
            }}
        }}

        document.addEventListener("keydown", function(e) {{
            if (e.ctrlKey || e.altKey || e.metaKey) {{
                clearG();
                return;
            }}
            if (isEditableTarget(e.target) || isEditableTarget(document.activeElement)) {{
                clearG();
                return;
            }}

            var key = e.key;
            if (key === "g") {{
                if (pendingG) {{
                    e.preventDefault();
                    clearG();
                    window.scrollTo({{ top: 0, behavior: scrollBehavior() }});
                }} else {{
                    pendingG = true;
                    gTimer = setTimeout(clearG, 550);
                }}
                return;
            }}

            clearG();

            if (key === "j") {{
                e.preventDefault();
                window.scrollBy({{ top: 88, behavior: "auto" }});
            }} else if (key === "k") {{
                e.preventDefault();
                window.scrollBy({{ top: -88, behavior: "auto" }});
            }} else if (key === "d") {{
                e.preventDefault();
                window.scrollBy({{ top: Math.round(window.innerHeight * 0.5), behavior: scrollBehavior() }});
            }} else if (key === "u") {{
                e.preventDefault();
                window.scrollBy({{ top: -Math.round(window.innerHeight * 0.5), behavior: scrollBehavior() }});
            }} else if (key === "G") {{
                e.preventDefault();
                window.scrollTo({{ top: document.documentElement.scrollHeight, behavior: scrollBehavior() }});
            }} else if (key === "/") {{
                e.preventDefault();
                postToGtk({{ type: "open-search" }});
            }} else if (key === "]") {{
                e.preventDefault();
                jumpHeading(1);
            }} else if (key === "[") {{
                e.preventDefault();
                jumpHeading(-1);
            }}
        }});
    }}

    /* ---------------------------------------------------------------------
     * 9. Scroll / Section / Watch-Follow Restoration & Host Helpers
     * ------------------------------------------------------------------- */
    function findSectionHeading(query) {{
        if (!query) return null;
        var exact = document.getElementById(query);
        if (exact) return exact;

        var needle = String(query).trim().toLowerCase();
        var needleSlug = slugifyText(needle);
        var headings = getDocumentHeadings();
        var partial = null;
        for (var i = 0; i < headings.length; i++) {{
            var h = headings[i];
            var hId = (h.id || "").toLowerCase();
            var hText = cleanHeadingText(h).toLowerCase();
            if (hId === needle || hId === needleSlug || hText === needle) {{
                return h;
            }}
            if (!partial && (hText.indexOf(needle) !== -1 || hId.indexOf(needleSlug) !== -1)) {{
                partial = h;
            }}
        }}
        return partial;
    }}

    function restoreInitialPosition() {{
        if (userScrolled) return;

        if (CONFIG.followChanged) {{
            var changed = document.querySelector('[data-changed="true"]');
            if (changed) {{
                changed.scrollIntoView({{ behavior: "auto", block: "center" }});
                return;
            }}
        }}

        if (CONFIG.initialSection) {{
            var target = findSectionHeading(CONFIG.initialSection);
            if (target) {{
                target.scrollIntoView({{ behavior: "auto", block: "start" }});
                return;
            }}
        }}

        if (CONFIG.initialScrollRatio > 0) {{
            var maxScroll = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
            if (maxScroll > 0) {{
                window.scrollTo({{
                    top: Math.round(CONFIG.initialScrollRatio * maxScroll),
                    behavior: "auto"
                }});
            }}
        }}
    }}

    window.__mdv = {{
        scrollToSlug: function(slug) {{
            var el = findSectionHeading(slug);
            if (el) {{
                el.scrollIntoView({{ behavior: scrollBehavior(), block: "start" }});
                return true;
            }}
            return false;
        }},
        scrollToRatio: function(ratio) {{
            var clamped = Math.max(0, Math.min(1, Number(ratio) || 0));
            var maxScroll = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
            window.scrollTo({{ top: Math.round(clamped * maxScroll), behavior: "auto" }});
        }},
        scrollToChanged: function() {{
            var el = document.querySelector('[data-changed="true"]');
            if (el) {{
                el.scrollIntoView({{ behavior: scrollBehavior(), block: "center" }});
                return true;
            }}
            return false;
        }}
    }};

    function init() {{
        renderMath();
        setupCodeBlocks();
        setupHeadingAnchors();
        setupTaskCheckboxes();
        setupSelectionCommentPill();
        setupVimNavigation();
        setupScrollTracker();

        var mermaidDone = renderMermaidDiagrams();
        requestAnimationFrame(function() {{
            restoreInitialPosition();
            mermaidDone.then(function() {{
                requestAnimationFrame(function() {{
                    restoreInitialPosition();
                    restoredInitialView = true;
                    emitScrollUpdate();
                }});
            }});
        }});
    }}

    if (document.readyState === "loading") {{
        document.addEventListener("DOMContentLoaded", init);
    }} else {{
        init();
    }}
}})();
"""
