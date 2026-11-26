#!/usr/bin/env python3
"""Executable CLI entry point shim for md-viewer v2."""

from __future__ import annotations

import sys

from mdviewer.cli import main

if __name__ == "__main__":
    sys.exit(main())
