import sys


if len(sys.argv) > 1 and sys.argv[1] == "--apply-update":
    from nvr_app.updater import run_update_helper

    raise SystemExit(run_update_helper(sys.argv))

from nvr_app.main import main


if __name__ == "__main__":
    raise SystemExit(main())

