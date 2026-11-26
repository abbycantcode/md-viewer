# Security Policy

## Supported Versions

Security fixes are applied to the latest release on `main`:

| Version | Supported |
| --- | --- |
| `2.x` (`main`) | Yes |
| `< 2.0` | No |

## Reporting a Vulnerability

Please report security vulnerabilities privately using **GitHub Security Advisories**:

- Open a private report at <https://github.com/abbycantcode/Markveil/security/advisories/new>

Please **do not** open public issues or pull requests for undisclosed security vulnerabilities.

When reporting, include as much of the following as possible:

- A clear description of the vulnerability and its potential impact.
- Minimal reproduction steps or a proof-of-concept Markdown/input file.
- Your environment details (Linux distribution, GTK3 / WebKit2GTK version, and Markveil commit or version).

We aim to acknowledge reports promptly, validate the issue, and coordinate a fix before public disclosure.

## Threat Model & Security Invariants

Markveil is designed to render untrusted local Markdown, technical files, and coding-agent artifacts offline inside a hardened GTK3 + WebKit2 desktop context. The following invariants are enforced across the codebase and covered by automated tests:

1. **Per-render Content Security Policy (CSP) nonces.** Every document render generates a fresh cryptographic nonce (`secrets.token_urlsafe(16)`) and enforces `default-src 'none'`, `script-src 'nonce-<nonce>'`, `connect-src 'none'`, `media-src 'none'`, `object-src 'none'`, and `frame-src 'none'`.
2. **HTMLParser allowlist sanitization.** `mdviewer/sanitizer.py` parses rendered HTML with Python's `html.parser.HTMLParser` (never regex stripping). It drops active and dangerous tags along with their contents (`script`, `style`, `iframe`, `frame`, `frameset`, `object`, `embed`, `applet`, `noscript`, `template`, `textarea`, `select`, `form`, `meta`, `base`, `link`, `svg`), removes all `on*` event attributes, `srcdoc`, `formaction`, and arbitrary inline `style` attributes (permitting only `text-align` on `th`/`td`), limits `<input>` to task-list checkboxes, and rejects `javascript:`, `vbscript:`, `data:text/html`, and `data:image/svg+xml` URLs.
3. **Strict Mermaid & post-sanitization hydration.** KaTeX math and Mermaid diagram payloads are restored from escaped attributes only after HTML sanitization, and Mermaid runs with `securityLevel: "strict"`.
4. **WebKit2 process & navigation isolation.** WebKit2 views enforce `allow_universal_access_from_file_urls = False` and `enable_page_cache = False`. External links are delegated to the system browser via `decide-policy` rather than navigated in-view.
5. **Remote image gate & URL normalization.** Remote `http:`, `https:`, and protocol-relative `//` image sources are blocked by default (`allow_remote_images = False`) and rewritten to `data-blocked-src` placeholders until explicitly allowed. Backslashes outside `data:` URIs are normalized to `/` prior to scheme classification to prevent URL smuggling.
6. **Agentic environment scanner denylists.** `mdviewer/agentic_env.py` skips session, transcript, cache, log, and VCS directories (such as `sessions`, `archived_sessions`, `brain`, `conversations`, `projects`, `chats`, `history`, `telemetry`, `cache`, `logs`, `.git`, `node_modules`, `.venv`, and `worktrees`), excludes sensitive filename patterns (`*credentials*`, `*auth*`, `*secret*`, `*token*`, `*accounts*`, `.env*`, `*.sqlite*`, `*.db`, `*.jsonl`, `*.key`, `*.pem`), caps traversal at depth 4 and head reads at 2,048 bytes, tracks canonical real paths to prevent symlink cycles, and never reads the bodies of config files.
7. **Safe local CLI execution.** Local agent CLI invocations run with `shell=False`, reject desktop GUI binaries, and bound document context payloads.
