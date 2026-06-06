"""PyInstaller entry point for the frozen build.

Mirrors ``python -m playstation_studio`` but as a plain script so PyInstaller
can freeze it. Also handles the ``--run-mkpfs`` self re-invocation used by the
PS5 compressor when there is no system Python.
"""

import multiprocessing
import sys


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--run-mkpfs":
        import runpy
        sys.argv = ["mkpfs", *sys.argv[2:]]
        runpy.run_module("mkpfs", run_name="__main__", alter_sys=True)
        return 0
    from playstation_studio.app import main as app_main
    return app_main()


if __name__ == "__main__":
    # MUST be first: in a frozen build, mkpfs spawns compression workers by
    # re-launching THIS executable. freeze_support() makes those re-launches
    # act as multiprocessing workers instead of re-opening the app/CLI.
    multiprocessing.freeze_support()
    raise SystemExit(main())
