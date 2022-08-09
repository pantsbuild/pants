# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import importlib.machinery
import logging
import os
import runpy
import sys
import zipimport

_logger = logging.getLogger(__name__)


def bootstrap_pyoxidizer() -> None:
    if is_oxidized:
        _logger.info("Pants is running as a PyOxidizer binary.")


# Provide the `is_oxidized` symbol, to allow for workarounds in Pants code where we use things
# that don't work under PyOxidizer's custom importer. `oxidized_importer` is only accessible
# in Pants under PyOxidizer, so an import failure will occur if we're not oxidized.
try:
    import oxidized_importer  # type: ignore # pants: no-infer-dep # noqa: F401

    is_oxidized = True
except ModuleNotFoundError:
    is_oxidized = False


if is_oxidized and not sys.argv[0]:
    # A not insignificant amount of Pants code relies on `sys.argv[0]`, which is modified in an
    # invalid way by python's `pymain_run_module` support. For our purposes, the executable
    # distribution is the correct `argv[0]`.
    # See https://github.com/indygreg/PyOxidizer/issues/307
    sys.argv[0] = sys.executable


def pex_main() -> bool:

    with open("/Users/chrisjrn/src/pants/oxidized-invocations.txt", "a") as f:
        import datetime

        f.write(f"{datetime.datetime.now()}: {sys.argv=} {sys.path=}\n")

    if sys.argv[1] == "./pex":
        run_as_pex()
        return True

    if sys.argv[1] == "-sE" and sys.argv[2].endswith("/pex"):
        print("bloop", file=sys.stderr)
        run_as_pip()
        return True

    if len(sys.argv) == 4 and sys.argv[1:3] == ["-s", "-c"]:
        run_as_dash_c()
        return True

    if ("-m", "venv") in zip(sys.argv, sys.argv[1:]):
        run_as_venv()
        return True

    return False


def prepare_import_machinery():
    print(f"pex main? {sys.version_info=} {sys.argv=}", flush=True)

    # pex relies heavily on `__file__`, which the Oxidized importer does not
    # believe in. This reinstates the default Python import machinery before
    # loading and running `pex`, but keeps the PyOxidizer machinery at lowest
    # priority, so we can still load interned `.py` sources (e.g. the stdlib)
    sys.meta_path = [
        importlib.machinery.BuiltinImporter,
        importlib.machinery.FrozenImporter,
        importlib.machinery.PathFinder,
    ] + sys.meta_path
    sys.path_hooks = [
        zipimport.zipimporter,
        importlib.machinery.FileFinder.path_hook(
            (importlib.machinery.ExtensionFileLoader, [".cpython-39-darwin.so", ".abi3.so", ".so"]),
            (importlib.machinery.SourceFileLoader, [".py"]),
            (importlib.machinery.SourcelessFileLoader, [".pyc"]),
        ),
    ] + sys.path_hooks


def run_as_pex():
    prepare_import_machinery()
    g = {}
    f = runpy.run_path("./pex", init_globals=g)
    del sys.argv[1]
    # sys.argv += ["-v"] * 3
    f["bootstrap_pex"]("./pex")
    sys.exit(0)


def run_as_venv():
    prepare_import_machinery()
    index = sys.argv.index("-m")

    import venv

    venv.__file__ = "EXTREMELY/FLAH/BLAH"

    sys.argv[1:] = sys.argv[index + 2 :]
    runpy.run_module("venv")
    sys.exit(0)


def run_as_dash_c():
    prepare_import_machinery()
    print(f"{os.environ=}", file=sys.stderr)
    if "PEX" in os.environ:
        # Get pex into the modules cache
        pex = runpy.run_path(os.environ["PEX"])
        pex["bootstrap_pex"](os.environ["PEX"], execute=False)

    index = sys.argv.index("-c")
    exec(sys.argv[index + 1], {}, {})
    sys.exit(0)


def run_as_pip():
    prepare_import_machinery()
    print("floop", file=sys.stderr)

    start_path = os.path.join(os.path.dirname(sys.argv[2]), "lib")
    ver = sys.version_info
    py_name = f"python{ver.major}.{ver.minor}"
    for (dirname, _, _) in os.walk(start_path):
        if dirname.endswith(py_name) or dirname.endswith(os.path.join(py_name, "site-packages")):
            sys.path.append(dirname)

    del sys.argv[1:3]
    runpy.run_module(mod_name="pip", run_name="__main__", alter_sys=True)
    sys.exit(0)
