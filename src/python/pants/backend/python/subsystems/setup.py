# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import enum
import logging
import os
from typing import Iterable, Iterator, Optional, cast

from pants.option.custom_types import file_option
from pants.option.subsystem import Subsystem
from pants.util.docutil import doc_url
from pants.util.memo import memoized_property
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
                "Mutually exclusive with `[python].enable_resolves`."
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
            type=str,
            metavar="<file>",
            mutually_exclusive_group="lockfile",
            help="Deprecated.",
            removal_version="2.11.0.dev0",
            removal_hint=(
                "Instead, use the improved `[python].experimental_resolves` mechanism. Read its "
                "help message for more information.\n\n"
                "If you want to keep using a single resolve like before, update "
                "`[python].experimental_resolves` with a name for the resolve and the path to "
                "its lockfile, or use the default. Then make sure that "
                "`[python].experimental_default_resolve` is set to that resolve name."
            ),
        )
        register(
            "--enable-resolves",
            advanced=True,
            type=bool,
            default=False,
            mutually_exclusive_group="lockfile",
            help=(
                "Set to true to enable the multiple resolves mechanism. See "
                "`[python].experimental_resolves` for an explanation of this feature.\n\n"
                "Mutually exclusive with `[python].requirement_constraints`."
            ),
        )
        register(
            "--experimental-resolves",
            advanced=True,
            type=dict,
            default={"python-default": "3rdparty/python/default_lock.txt"},
            help=(
                "A mapping of logical names to lockfile paths used in your project.\n\n"
                "Many organizations only need a single resolve for their whole project, which is "
                "a good default and the simplest thing to do. However, you may need multiple "
                "resolves, such as if you use two conflicting versions of a requirement in "
                "your repository.\n\n"
                "For now, Pants only has first-class support for disjoint resolves, meaning that "
                "you cannot ergonomically set a `python_source` target, for example, to work "
                "with multiple resolves. Practically, this means that you cannot yet reuse common "
                "code, such as util files, across projects using different resolves. Support for "
                "overlapping resolves is coming soon.\n\n"
                "If you only need a single resolve, run `./pants generate-lockfiles` to generate "
                "the lockfile.\n\n"
                "If you need multiple resolves:\n\n"
                "  1. Via this option, define multiple resolve "
                "names and their lockfile paths. The names should be meaningful to your "
                "repository, such as `data-science` or `pants-plugins`.\n"
                "  2. Set the default with "
                "`[python].experimental_default_resolve`.\n"
                "  3. Update your `python_requirement` targets with the "
                "`experimental_compatible_resolves` field to declare which resolve(s) they should "
                "be available in. They default to `[python].experimental_default_resolve`, so you "
                "only need to update targets that you want in non-default resolves. "
                "(Often you'll set this via the `python_requirements` or `poetry_requirements` "
                "target generators)\n"
                "  4. Run `./pants generate-lockfiles` to generate the lockfiles. If the results "
                "aren't what you'd expect, adjust the prior step.\n"
                "  5. Update any targets like `python_source` / `python_sources`, "
                "`python_test` / `python_tests`, and `pex_binary` which need to set a non-default "
                "resolve with the `experimental_resolve` field.\n\n"
                "Only applies if `[python].enable_resolves` is true.\n\n"
                "This option is experimental and may change without the normal deprecation policy."
            ),
        )
        register(
            "--experimental-default-resolve",
            advanced=True,
            type=str,
            default="python-default",
            help=(
                "The default value used for the `experimental_resolve` and "
                "`experimental_compatible_resolves` fields.\n\n"
                "The name must be defined as a resolve in `[python].experimental_resolves`.\n\n"
                "This option is experimental and may change without the normal deprecation policy."
            ),
        )
        register(
            "--experimental-resolves-to-interpreter-constraints",
            advanced=True,
            type=dict,
            default={},
            help=(
                "Override the interpreter constraints to use when generating a resolve's lockfile "
                "with the `generate-lockfiles` goal.\n\n"
                "By default, each resolve from `[python].experimental_resolves` will use your "
                "global interpreter constraints set in `[python].interpreter_constraints`. With "
                "this option, you can override each resolve to use certain interpreter "
                "constraints, such as `{'data-science': ['==3.8.*']}`.\n\n"
                "Pants will validate that the interpreter constraints of your code using a "
                "resolve are compatible with that resolve's own constraints. For example, if your "
                "code is set to use ['==3.9.*'] via the `interpreter_constraints` field, but it's "
                "also using a resolve whose interpreter constraints are set to ['==3.7.*'], then "
                "Pants will error explaining the incompatibility.\n\n"
                "The keys must be defined as resolves in `[python].experimental_resolves`.\n\n"
                "This option is experimental and may change without the normal deprecation policy."
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
            removal_version="2.11.0.dev0",
            removal_hint="Now set automatically based on the amount of concurrency available.",
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
    def enable_resolves(self) -> bool:
        return cast(bool, self.options.enable_resolves)

    @property
    def resolves(self) -> dict[str, str]:
        return cast("dict[str, str]", self.options.experimental_resolves)

    @property
    def default_resolve(self) -> str:
        return cast(str, self.options.experimental_default_resolve)

    @memoized_property
    def resolves_to_interpreter_constraints(self) -> dict[str, tuple[str, ...]]:
        result = {}
        for resolve, ics in self.options.experimental_resolves_to_interpreter_constraints.items():
            if resolve not in self.resolves:
                raise KeyError(
                    "Unrecognized resolve name in the option "
                    f"`[python].experimental_resolves_to_interpreter_constraints`: {resolve}. Each "
                    "key must be one of the keys in `[python].experimental_resolves`: "
                    f"{sorted(self.resolves.keys())}"
                )
            result[resolve] = tuple(ics)
        return result

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

    @property
    def manylinux(self) -> str | None:
        manylinux = cast(Optional[str], self.options.resolver_manylinux)
        if manylinux is None or manylinux.lower() in ("false", "no", "none"):
            return None
        return manylinux

    @property
    def manylinux_pex_args(self) -> Iterator[str]:
        if self.manylinux:
            yield "--manylinux"
            yield self.manylinux
        else:
            yield "--no-manylinux"

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
