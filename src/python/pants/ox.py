# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import contextlib
import functools
import importlib.machinery
import logging
import os
import runpy
import site
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
    """Detect whether some process is trying to invoke this binary as (or as a Child of) Pex:

    In order to fetch 3rd-party plugins that will be compatible with Pants' environment, Pants will
    invoke Pex using the same binary that Pants was loaded with. In a non-PyOxidized environment,
    this is a working Python interpreter. In PyOxidized environments, it's the binary itself. Pex
    subsequently runs a bunch of Python processes in order to invoke `pip`, `venv`, and `python -c`.
    This looks for certain command line switches, and attempt to invoke the relevant modules that
    those switches indicate. Each of the functions below will get the import machinery and
    `sys.modules` content into a state where the relevant invocations will run in a more-or-less
    "normal" manner (at least as far as `pex` is concerned).
    """

    if len(sys.argv) < 2:
        return False

    if sys.argv[1] == "./pex":
        # `pex` itself is being called to assemble a pex package
        _run_as_pex()
        return True

    if sys.argv[1] == "-sE" and sys.argv[2].endswith("/pex"):
        _run_pex_venv()
        return True

    if len(sys.argv) == 4 and sys.argv[1:3] == ["-s", "-c"]:
        _run_as_dash_c()
        return True

    if ("-m", "venv") in zip(sys.argv, sys.argv[1:]):
        _run_as_venv()
        return True

    return False


@contextlib.contextmanager
def traditional_import_machinery():
    # pex relies heavily on `__file__`, which the Oxidized importer does not
    # believe in. This reinstates the default Python import machinery before
    # loading and running `pex`, but keeps the PyOxidizer machinery at lowest
    # priority, so we can still load interned `.py` sources (e.g. the stdlib)

    old_sys_meta_path = sys.meta_path
    old_sys_path_hooks = sys.path_hooks

    if is_oxidized:
        sys.meta_path = [
            importlib.machinery.BuiltinImporter,
            importlib.machinery.FrozenImporter,
            importlib.machinery.PathFinder,
        ] + sys.meta_path
        sys.path_hooks = [
            zipimport.zipimporter,
            importlib.machinery.FileFinder.path_hook(
                (
                    importlib.machinery.ExtensionFileLoader,
                    [".cpython-39-darwin.so", ".abi3.so", ".so"],
                ),
                (importlib.machinery.SourceFileLoader, [".py"]),
                (importlib.machinery.SourcelessFileLoader, [".pyc"]),
            ),
        ] + sys.path_hooks

    try:
        yield
    finally:
        sys.meta_path = old_sys_meta_path
        sys.path_hooks = old_sys_path_hooks


def use_traditional_import_machinery(f):
    @functools.wraps(f)
    def wrapped(*a, **k):
        with traditional_import_machinery():
            return f(*a, **k)

    return wrapped


@use_traditional_import_machinery
def _run_as_pex():
    g = {}
    f = runpy.run_path("./pex", init_globals=g)
    del sys.argv[1]
    f["bootstrap_pex"]("./pex")
    sys.exit(0)


@use_traditional_import_machinery
def _run_as_venv():
    index = sys.argv.index("-m")

    import venv

    # `venv` is supplied by the oxidized importer (the stdlib is embedded in the rust binary)
    # but uses the `__file__` attribute to find the location of `activate` scripts. These scripts
    # are not needed by pex, so we're setting the value to something bogus just to prevent
    # subsequent exceptions.
    venv.__file__ = "SOMETHING/THAT/IS/NOT/NONE"

    sys.argv[1:] = sys.argv[index + 2 :]
    runpy.run_module("venv")
    sys.exit(0)


@use_traditional_import_machinery
def _run_as_dash_c():
    if "PEX" in os.environ:
        # Get pex into the modules cache
        pex = runpy.run_path(os.environ["PEX"])
        pex["bootstrap_pex"](os.environ["PEX"], execute=False)

    index = sys.argv.index("-c")
    exec(sys.argv[index + 1], {}, {})
    sys.exit(0)


@use_traditional_import_machinery
def _run_pex_venv():
    path_to_run = sys.argv[2]
    site.PREFIXES = [os.path.dirname(path_to_run)]
    site.addsitepackages(set())
    del sys.argv[1:3]
    runpy.run_path(path_to_run, run_name="__main__")
    sys.exit(0)
