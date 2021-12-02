# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import enum
import logging
import os
from typing import Iterable, Optional, cast

from pants.engine.environment import Environment
from pants.option.custom_types import file_option
from pants.option.subsystem import Subsystem
from pants.python.binaries import PythonBootstrap
from pants.util.docutil import doc_url
from pants.util.memo import memoized_method
from pants.util.osutil import CPU_COUNT

logger = logging.getLogger(__name__)


@enum.unique
class InvalidLockfileBehavior(enum.Enum):
    error = "error"
    ignore = "ignore"
    warn = "warn"


class PythonSetup(Subsystem):
    options_scope = "python"
    help = "Options for Pants's Python backend."

    deprecated_options_scope = "python-setup"
    deprecated_options_scope_removal_version = "2.10.0.dev0"

    default_interpreter_constraints = ["CPython>=3.6,<4"]
    default_interpreter_universe = ["2.7", "3.5", "3.6", "3.7", "3.8", "3.9", "3.10"]

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--interpreter-constraints",
            advanced=True,
            type=list,
            default=PythonSetup.default_interpreter_constraints,
            metavar="<requirement>",
            help=(
                "The Python interpreters your codebase is compatible with.\n\nSpecify with "
                "requirement syntax, e.g. 'CPython>=2.7,<3' (A CPython interpreter with version "
                ">=2.7 AND version <3) or 'PyPy' (A pypy interpreter of any version). Multiple "
                "constraint strings will be ORed together.\n\nThese constraints are used as the "
                "default value for the `interpreter_constraints` field of Python targets."
            ),
        )
        register(
            "--interpreter-versions-universe",
            advanced=True,
            type=list,
            default=cls.default_interpreter_universe,
            help=(
                "All known Python major/minor interpreter versions that may be used by either "
                "your code or tools used by your code.\n\n"
                "This is used by Pants to robustly handle interpreter constraints, such as knowing "
                "when generating lockfiles which Python versions to check if your code is "
                "using.\n\n"
                "This does not control which interpreter your code will use. Instead, to set your "
                "interpreter constraints, update `[python].interpreter_constraints`, the "
                "`interpreter_constraints` field, and relevant tool options like "
                "`[isort].interpreter_constraints` to tell Pants which interpreters your code "
                f"actually uses. See {doc_url('python-interpreter-compatibility')}.\n\n"
                "All elements must be the minor and major Python version, e.g. '2.7' or '3.10'. Do "
                "not include the patch version.\n\n"
            ),
        )
        register(
            "--requirement-constraints",
            advanced=True,
            type=file_option,
            mutually_exclusive_group="lockfile",
            help=(
                "When resolving third-party requirements for your own code (vs. tools you run), "
                "use this constraints file to determine which versions to use.\n\n"
                "This only applies when resolving user requirements, rather than tools you run "
                "like Black and Pytest. To constrain tools, set `[tool].lockfile`, e.g. "
                "`[black].lockfile`.\n\n"
                "See https://pip.pypa.io/en/stable/user_guide/#constraints-files for more "
                "information on the format of constraint files and how constraints are applied in "
                "Pex and pip.\n\n"
                "Mutually exclusive with `[python].experimental_lockfile`."
            ),
        )
        register(
            "--resolve-all-constraints",
            advanced=True,
            default=True,
            type=bool,
            help=(
                "If enabled, when resolving requirements, Pants will first resolve your entire "
                "constraints file as a single global resolve. Then, if the code uses a subset of "
                "your constraints file, Pants will extract the relevant requirements from that "
                "global resolve so that only what's actually needed gets used. If disabled, Pants "
                "will not use a global resolve and will resolve each subset of your requirements "
                "independently."
                "\n\nUsually this option should be enabled because it can result in far fewer "
                "resolves."
                "\n\nRequires [python].requirement_constraints to be set."
            ),
        )
        register(
            "--experimental-lockfile",
            advanced=True,
            # TODO(#11719): Switch this to a file_option once env vars can unset a value.
            type=str,
            metavar="<file>",
            mutually_exclusive_group="constraints",
            help=(
                "The lockfile to use when resolving requirements for your own code (vs. tools you "
                "run).\n\n"
                "This is highly experimental and will change, including adding support for "
                "multiple lockfiles. This option's behavior may change without the normal "
                "deprecation cycle.\n\n"
                "To generate a lockfile, activate the backend `pants.backend.experimental.python`"
                "and run `./pants generate-user-lockfile ::`.\n\n"
                "Mutually exclusive with `[python].requirement_constraints`."
            ),
        )
        register(
            "--experimental-resolves-to-lockfiles",
            advanced=True,
            type=dict,
            help=(
                "A mapping of logical names to lockfile paths used in your project, e.g. "
                "`{ default = '3rdparty/default_lockfile.txt', py2 = '3rdparty/py2.txt' }`.\n\n"
                "To generate a lockfile, run `./pants generate-lockfiles --resolve=<name>` or "
                "`./pants generate-lockfiles` to generate for all resolves (including tool "
                "lockfiles).\n\n"
                "This is highly experimental and will likely change."
            ),
        )
        register(
            "--invalid-lockfile-behavior",
            advanced=True,
            type=InvalidLockfileBehavior,
            default=InvalidLockfileBehavior.error,
            help=(
                "The behavior when a lockfile has requirements or interpreter constraints that are "
                "not compatible with what the current build is using.\n\n"
                "We recommend keeping the default of `error` for CI builds."
            ),
        )
        register(
            "--run-against-entire-lockfile",
            advanced=True,
            default=False,
            type=bool,
            help=(
                "If enabled, when running binaries, tests, and repls, Pants will use the entire "
                "lockfile/constraints file instead of just the relevant subset. This can improve "
                "performance and reduce cache size, but has two consequences: 1) All cached test "
                "results will be invalidated if any requirement in the lockfile changes, rather "
                "than just those that depend on the changed requirement. 2) Requirements unneeded "
                "by a test/run/repl will be present on the sys.path, which might in rare cases "
                "cause their behavior to change.\n\n"
                "This option does not affect packaging deployable artifacts, such as "
                "PEX files, wheels and cloud functions, which will still use just the exact "
                "subset of requirements needed."
            ),
        )
        register(
            "--interpreter-search-paths",
            advanced=True,
            type=list,
            default=["<PYENV>", "<PATH>"],
            metavar="<binary-paths>",
            removal_version="2.10.0.dev0",
            removal_hint=("Moved to `[python-bootstrap] search_path`."),
            help=(
                "A list of paths to search for Python interpreters that match your project's "
                "interpreter constraints.\n\n"
                "You can specify absolute paths to interpreter binaries "
                "and/or to directories containing interpreter binaries. The order of entries does "
                "not matter.\n\n"
                "The following special strings are supported:\n\n"
                "* `<PATH>`, the contents of the PATH env var\n"
                "* `<ASDF>`, all Python versions currently configured by ASDF "
                "`(asdf shell, ${HOME}/.tool-versions)`, with a fallback to all installed versions\n"
                "* `<ASDF_LOCAL>`, the ASDF interpreter with the version in "
                "BUILD_ROOT/.tool-versions\n"
                "* `<PYENV>`, all Python versions under $(pyenv root)/versions\n"
                "* `<PYENV_LOCAL>`, the Pyenv interpreter with the version in "
                "BUILD_ROOT/.python-version\n"
                "* `<PEXRC>`, paths in the PEX_PYTHON_PATH variable in /etc/pexrc or ~/.pexrc"
            ),
        )
        register(
            "--resolver-manylinux",
            advanced=True,
            type=str,
            default="manylinux2014",
            help="Whether to allow resolution of manylinux wheels when resolving requirements for "
            "foreign linux platforms. The value should be a manylinux platform upper bound, "
            "e.g.: 'manylinux2010', or else the string 'no' to disallow.",
        )
        register(
            "--resolver-jobs",
            type=int,
            default=CPU_COUNT // 2,
            default_help_repr="#cores/2",
            advanced=True,
            help=(
                "The maximum number of concurrent jobs to build wheels with.\n\nBecause Pants "
                "can run multiple subprocesses in parallel, the maximum total parallelism will be "
                "`--process-execution-{local,remote}-parallelism x --python-resolver-jobs`. "
                "\n\nSetting this option higher may result in better parallelism, but, if set too "
                "high, may result in starvation and Out of Memory errors."
            ),
        )

        register(
            "--tailor-ignore-solitary-init-files",
            type=bool,
            default=True,
            advanced=True,
            help="Don't tailor `python_sources` targets for solitary `__init__.py` files, as "
            "those usually exist as import scaffolding rather than true library code.\n\n"
            "Set to False if you commonly have packages containing real code in "
            "`__init__.py` and there are no other .py files in the package.",
        )

        register(
            "--tailor-requirements-targets",
            type=bool,
            default=True,
            advanced=True,
            help="Tailor python_requirements() targets for requirements files.",
        )

        register(
            "--tailor-pex-binary-targets",
            type=bool,
            default=True,
            advanced=True,
            help="Tailor pex_binary() targets for Python entry point files.",
        )

        register(
            "--macos-big-sur-compatibility",
            type=bool,
            default=False,
            help="If set, and if running on MacOS Big Sur, use macosx_10_16 as the platform "
            "when building wheels. Otherwise, the default of macosx_11_0 will be used. "
            "This may be required for pip to be able to install the resulting distribution "
            "on Big Sur.",
        )

    @property
    def interpreter_constraints(self) -> tuple[str, ...]:
        return tuple(self.options.interpreter_constraints)

    @property
    def interpreter_universe(self) -> tuple[str, ...]:
        return tuple(self.options.interpreter_versions_universe)

    @property
    def requirement_constraints(self) -> str | None:
        """Path to constraint file."""
        return cast("str | None", self.options.requirement_constraints)

    @property
    def lockfile(self) -> str | None:
        return cast("str | None", self.options.experimental_lockfile)

    @property
    def resolves_to_lockfiles(self) -> dict[str, str]:
        return cast("dict[str, str]", self.options.experimental_resolves_to_lockfiles)

    @property
    def invalid_lockfile_behavior(self) -> InvalidLockfileBehavior:
        return cast(InvalidLockfileBehavior, self.options.invalid_lockfile_behavior)

    @property
    def run_against_entire_lockfile(self) -> bool:
        return cast(bool, self.options.run_against_entire_lockfile)

    @property
    def resolve_all_constraints(self) -> bool:
        return cast(bool, self.options.resolve_all_constraints)

    def resolve_all_constraints_was_set_explicitly(self) -> bool:
        return not self.options.is_default("resolve_all_constraints")

    @memoized_method
    def interpreter_search_paths(self, env: Environment):
        # TODO: When the `interpreter_search_paths` option is removed, callers who need the
        # interpreter search path should directly use `PythonBootstrap.interpreter_search_path`.
        return PythonBootstrap.expand_interpreter_search_paths(
            self.options.interpreter_search_paths, env
        )

    @property
    def manylinux(self) -> str | None:
        manylinux = cast(Optional[str], self.options.resolver_manylinux)
        if manylinux is None or manylinux.lower() in ("false", "no", "none"):
            return None
        return manylinux

    @property
    def resolver_jobs(self) -> int:
        return cast(int, self.options.resolver_jobs)

    @property
    def tailor_ignore_solitary_init_files(self) -> bool:
        return cast(bool, self.options.tailor_ignore_solitary_init_files)

    @property
    def tailor_requirements_targets(self) -> bool:
        return cast(bool, self.options.tailor_requirements_targets)

    @property
    def tailor_pex_binary_targets(self) -> bool:
        return cast(bool, self.options.tailor_pex_binary_targets)

    @property
    def macos_big_sur_compatibility(self) -> bool:
        return cast(bool, self.options.macos_big_sur_compatibility)

    @property
    def scratch_dir(self):
        return os.path.join(self.options.pants_workdir, *self.options_scope.split("."))

    def compatibility_or_constraints(self, compatibility: Iterable[str] | None) -> tuple[str, ...]:
        """Return either the given `compatibility` field or the global interpreter constraints.

        If interpreter constraints are supplied by the CLI flag, return those only.
        """
        if self.options.is_flagged("interpreter_constraints"):
            return self.interpreter_constraints
        return tuple(compatibility or self.interpreter_constraints)

    def compatibilities_or_constraints(
        self, compatibilities: Iterable[Iterable[str] | None]
    ) -> tuple[str, ...]:
        return tuple(
            constraint
            for compatibility in compatibilities
            for constraint in self.compatibility_or_constraints(compatibility)
        )
