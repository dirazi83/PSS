import sys


def _maybe_run_mkpfs() -> bool:
    """When invoked as ``… --run-mkpfs <args>``, act as the mkpfs CLI.

    This lets a frozen (PyInstaller) build re-invoke its own executable to run
    the bundled mkpfs engine, since there is no system ``python`` to call.
    """
    if len(sys.argv) > 1 and sys.argv[1] == "--run-mkpfs":
        import runpy
        sys.argv = ["mkpfs", *sys.argv[2:]]
        runpy.run_module("mkpfs", run_name="__main__", alter_sys=True)
        return True
    return False


if __name__ == "__main__":
    if _maybe_run_mkpfs():
        raise SystemExit(0)
    from .app import main
    raise SystemExit(main())
