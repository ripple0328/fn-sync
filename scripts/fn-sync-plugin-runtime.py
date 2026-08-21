#!/usr/bin/env python3
"""Single executable entry point for the self-contained Omarchy runtime."""

from __future__ import annotations

import sys
from collections.abc import Sequence

import fn_sync_discover

import fnsync


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["plugin-discover"]:
        return fn_sync_discover.main()
    return fnsync.main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
