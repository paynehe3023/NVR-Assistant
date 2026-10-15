from __future__ import annotations

import sys

from nvr_app.updater import run_update_helper


def main(argv: list[str] | None = None) -> int:
    """Compatibility entry point for the retired standalone updater."""
    return run_update_helper(sys.argv if argv is None else argv)


if __name__ == "__main__":
    raise SystemExit(main())
