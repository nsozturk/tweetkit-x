#!/usr/bin/env python3
"""Standalone cookie importer (works from a clone without installing).

    python scripts/import_cookie.py --paste                       # paste Cookie header
    python scripts/import_cookie.py --file x.com.har              # HAR
    python scripts/import_cookie.py --file storagedump_x.com.zip  # storage-dump zip
    python scripts/import_cookie.py --file dump.zip --keychain tweetkit

Thin wrapper over `tweetkit_x.cli` so `tweetkit import ...` and this behave the same.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tweetkit_x.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["import"] + sys.argv[1:]))
