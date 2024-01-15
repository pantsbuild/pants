# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import enum
import logging
import os
from typing import Iterable, List, Optional, TypeVar, cast

from packaging.utils import canonicalize_name

from pants.core.goals.generate_lockfiles import UnrecognizedResolveNamesError
from pants.option.errors import OptionsError
from pants.option.option_types import (
    BoolOption,
    DictOption,
    EnumOption,
    FileOption,
    StrListOption,
    StrOption,
)
from pants.option.subsystem import Subsystem
from pants.util.docutil import bin_name, doc_url
from pants.util.memo import memoized_method, memoized_property
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


@enum.unique
class InvalidLockfileBehavior(enum.Enum):
    error = "error"
    ignore = "ignore"
    warn = "warn"


@enum.unique
class LockfileGenerator(enum.Enum):
    PEX = "pex"
    POETRY = "poetry"


RESOLVE_OPTION_KEY__DEFAULT = "__default__"

_T = TypeVar("_T")


class PythonSetup(Subsystem):
    options_scope = "python"
    help = "Options for Pants's Python backend."

    default_interpreter_universe = [
        "2.7",
        "3.5",
        "3.6",
        "3.7",
        "3.8",
        "3.9",
        "3.10",
        "3.11",
        "3.12",
    ]

    _interpreter_constraints = StrListOption(
        default=None,
        help=softwrap(
            """
            The Python interpreters your codebase is compatible with.

            These constraints are used as the default value for the `interpreter_constraints`
            field of Python targets.

            Specify with requirement syntax, e.g. `'CPython>=2.7,<3'` (A CPython interpreter with
            version >=2.7 AND version <3) or `'PyPy'` (A pypy interpreter of any version). Multiple
            constraint strings will be ORed together.
            """
        ),
        advanced=True,
        metavar="<requirement>",
    )

    @memoized_property
    def interpreter_constraints(self) -> tuple[str, ...]:
        if not self._interpreter_constraints:
            # TODO: This is a hacky affordance for Pants's own tests, dozens of which were
            #  written when Pants provided default ICs, and implicitly rely on that assumption.
            #  We'll probably want to find and modify all those tests to set an explicit IC, but
            #  that will take time.
            if "PYTEST_CURRENT_TEST" in os.environ:
                return (">=3.7,<4",)
            raise OptionsError(
                softwrap(
                    f"""\
                    You must explicitly specify the default Python interpreter versions your code
                    is intended to run against.

                    You specify these interpreter constraints using the `interpreter_constraints`
                    option in the `[python]` section of pants.toml.

                    We recommend constraining to a single interpreter minor version if you can,
                    e.g., `interpreter_constraints = ['==3.11.*']`, or at least a small number of
                    interpreter minor versions, e.g., `interpreter_constraints = ['>=3.10,<3.12']`.

                    Individual targets can override these default interpreter constraints,
                    if different parts of your codebase run against different python interpreter
                    versions in a single repo.

                    See {doc_url("python-interpreter-compatibility")} for details.
                    """
                ),
            )
        return self._interpreter_constraints

    interpreter_versions_universe = StrListOption(
        default=default_interpreter_universe,
        help=softwrap(
            f"""
            All known Python major/minor interpreter versions that may be used by either
            your code or tools used by your code.

            This is used by Pants to robustly handle interpreter constraints, such as knowing
            when generating lockfiles which Python versions to check if your code is using.

            This does not control which interpreter your code will use. Instead, to set your
            interpreter constraints, update `[python].interpreter_constraints`, the
            `interpreter_constraints` field, and relevant tool options like
            `[isort].interpreter_constraints` to tell Pants which interpreters your code
            actually uses. See {doc_url('python-interpreter-compatibility')}.

            All elements must be the minor and major Python version, e.g. `'2.7'` or `'3.10'`. Do
            not include the patch version.
            """
        ),
        advanced=True,
    )
    enable_resolves = BoolOption(
        default=False,
        help=softwrap(
            """
            Set to true to enable lockfiles for user code. See `[python].resolves` for an
            explanation of this feature.

            This option is mutually exclusive with `[python].requirement_constraints`. We strongly
            recommend using this option because it:

              1. Uses `--hash` to validate that all downloaded files are expected, which reduces\
                the risk of supply chain attacks.
              2. Enforces that all transitive dependencies are in the lockfile, whereas\
                constraints allow you to leave off dependencies. This ensures your build is more\
                stable and reduces the risk of supply chain attacks.
              3. Allows you to have multiple lockfiles in your repository.
            """
        ),
        advanced=True,
        mutually_exclusive_group="lockfile",
    )
    resolves = DictOption[str](
        default={"python-default": "3rdparty/python/default.lock"},
        help=softwrap(
            f"""
            A mapping of logical names to lockfile paths used in your project.

            Many organizations only need a single resolve for their whole project, which is
            a good default and often the simplest thing to do. However, you may need multiple
            resolves, such as if you use two conflicting versions of a requirement in
            your repository.

            If you only need a single resolve, run `{bin_name()} generate-lockfiles` to
            generate the lockfile.

            If you need multiple resolves:

              1. Via this option, define multiple resolve names and their lockfile paths.\
                The names should be meaningful to your repository, such as `data-science` or\
                `pants-plugins`.
              2. Set the default with `[python].default_resolve`.
              3. Update your `python_requirement` targets with the `resolve` field to declare which\
                resolve they should be available in. They default to `[python].default_resolve`,\
                so you only need to update targets that you want in non-default resolves.\
                (Often you'll set this via the `python_requirements` or `poetry_requirements`\
                target generators)
              4. Run `{bin_name()} generate-lockfiles` to generate the lockfiles. If the results\
                aren't what you'd expect, adjust the prior step.
              5. Update any targets like `python_source` / `python_sources`,\
                `python_test` / `python_tests`, and `pex_binary` which need to set a non-default\
                resolve with the `resolve` field.

            If a target can work with multiple resolves, you can either use the `parametrize`
            mechanism or manually create a distinct target per resolve. See {doc_url("targets")}
            for information about `parametrize`.

            For example:

                python_sources(
                    resolve=parametrize("data-science", "web-app"),
                )

            You can name the lockfile paths what you would like; Pants does not expect a
            certain file extension or location.

            Only applies if `[python].enable_resolves` is true.
            """
        ),
        advanced=True,
    )
    default_resolve = StrOption(
        default="python-default",
        help=softwrap(
            """
            The default value used for the `resolve` field.

            The name must be defined as a resolve in `[python].resolves`.
            """
        ),
        advanced=True,
    )
    default_run_goal_use_sandbox = BoolOption(
        default=True,
        help=softwrap(
            """
            The default value used for the `run_goal_use_sandbox` field of Python targets. See the
            relevant field for more details.
            """
        ),
    )
    pip_version = StrOption(
        default="23.1.2",
        help=softwrap(
            f"""
            Use this version of Pip for resolving requirements and generating lockfiles.

            The value used here must be one of the Pip versions supported by the underlying PEX
            version. See {doc_url("pex")} for details.

            N.B.: The `latest` value selects the latest of the choices listed by PEX which is not
            necessarily the latest Pip version released on PyPI.
            """
        ),
        advanced=True,
    )
    _resolves_to_interpreter_constraints = DictOption[List[str]](
        help=softwrap(
            """
            Override the interpreter constraints to use when generating a resolve's lockfile
            with the `generate-lockfiles` goal.

            By default, each resolve from `[python].resolves` will use your
            global interpreter constraints set in `[python].interpreter_constraints`. With
            this option, you can override each resolve to use certain interpreter
            constraints, such as `{'data-science': ['==3.8.*']}`.

            Warning: this does NOT impact the interpreter constraints used by targets within the
            resolve, which is instead set by the option `[python].interpreter_constraints` and the
            `interpreter_constraints` field. It only impacts how the lockfile is generated.

            Pants will validate that the interpreter constraints of your code using a
            resolve are compatible with that resolve's own constraints. For example, if your
            code is set to use `['==3.9.*']` via the `interpreter_constraints` field, but it's
            using a resolve whose interpreter constraints are set to `['==3.7.*']`, then
            Pants will error explaining the incompatibility.

            The keys must be defined as resolves in `[python].resolves`.
            """
        ),
        advanced=True,
    )
    _resolves_to_constraints_file = DictOption[str](
        help=softwrap(
            f"""
            When generating a resolve's lockfile, use a constraints file to pin the version of
            certain requirements. This is particularly useful to pin the versions of transitive
            dependencies of your direct requirements.

            See https://pip.pypa.io/en/stable/user_guide/#constraints-files for more information on
            the format of constraint files and how constraints are applied in Pex and pip.

            Expects a dictionary of resolve names from `[python].resolves` and Python tools (e.g.
            `black` and `pytest`) to file paths for
            constraints files. For example,
            `{{'data-science': '3rdparty/data-science-constraints.txt'}}`.
            If a resolve is not set in the dictionary, it will not use a constraints file.

            You can use the key `{RESOLVE_OPTION_KEY__DEFAULT}` to set a default value for all
            resolves.
            """
        ),
        advanced=True,
    )
    _resolves_to_no_binary = DictOption[List[str]](
        help=softwrap(
            f"""
            When generating a resolve's lockfile, do not use binary packages (i.e. wheels) for
            these 3rdparty project names.

            Expects a dictionary of resolve names from `[python].resolves` and Python tools (e.g.
            `black` and `pytest`) to lists of project names. For example,
            `{{'data-science': ['requests', 'numpy']}}`. If a resolve is not set in the dictionary,
            it will have no restrictions on binary packages.

            You can use the key `{RESOLVE_OPTION_KEY__DEFAULT}` to set a default value for all
            resolves.

            For each resolve, you can also use the value `:all:` to disable all binary packages:
            `{{'data-science': [':all:']}}`.

            Note that some packages are tricky to compile and may fail to install when this option
            is used on them. See https://pip.pypa.io/en/stable/cli/pip_install/#install-no-binary
            for details.
            """
        ),
        advanced=True,
    )
    _resolves_to_only_binary = DictOption[List[str]](
        help=softwrap(
            f"""
            When generating a resolve's lockfile, do not use source packages (i.e. sdists) for
            these 3rdparty project names, e.g `['django', 'requests']`.

            Expects a dictionary of resolve names from `[python].resolves` and Python tools (e.g.
            `black` and `pytest`) to lists of project names. For example,
            `{{'data-science': ['requests', 'numpy']}}`. If a resolve is not set in the dictionary,
            it will have no restrictions on source packages.

            You can use the key `{RESOLVE_OPTION_KEY__DEFAULT}` to set a default value for all
            resolves.

            For each resolve you can use the value `:all:` to disable all source packages:
            `{{'data-science': [':all:']}}`.

            Packages without binary distributions will fail to install when this option is used on
            them. See https://pip.pypa.io/en/stable/cli/pip_install/#install-only-binary for
            details.
            """
        ),
        advanced=True,
    )
    invalid_lockfile_behavior = EnumOption(
        default=InvalidLockfileBehavior.error,
        help=softwrap(
            """
            The behavior when a lockfile has requirements or interpreter constraints that are
            not compatible with what the current build is using.

            We recommend keeping the default of `error` for CI builds.

            Note that `warn` will still expect a Pants lockfile header, it only won't error if
            the lockfile is stale and should be regenerated.

            Use `ignore` to avoid needing a lockfile header at all, e.g. if you are manually
            managing lockfiles rather than using the `generate-lockfiles` goal.
            """
        ),
        advanced=True,
    )
    resolves_generate_lockfiles = BoolOption(
        default=True,
        help=softwrap(
            """
            If False, Pants will not attempt to generate lockfiles for `[python].resolves` when
            running the `generate-lockfiles` goal.

            This is intended to allow you to manually generate lockfiles for your own code,
            rather than using Pex lockfiles. For example, when adopting Pants in a project already
            using Poetry, you can use `poetry export --dev` to create a requirements.txt-style
            lockfile understood by Pants, then point `[python].resolves` to the file.

            If you set this to False, Pants will not attempt to validate the metadata headers
            for your user lockfiles. This is useful so that you can keep
            `[python].invalid_lockfile_behavior` to `error` or `warn` if you'd like so that tool
            lockfiles continue to be validated, while user lockfiles are skipped.

            Warning: it will likely be slower to install manually generated user lockfiles than Pex
            ones because Pants cannot as efficiently extract the subset of requirements used for a
            particular task. See the option `[python].run_against_entire_lockfile`.
            """
        ),
        advanced=True,
    )
    run_against_entire_lockfile = BoolOption(
        default=False,
        help=softwrap(
            """
            If enabled, when running binaries, tests, and repls, Pants will use the entire
            lockfile file instead of just the relevant subset.

            If you are using Pex lockfiles, we generally do not recommend this. You will already
            get similar performance benefits to this option, without the downsides.

            Otherwise, this option can improve performance and reduce cache size.
            But it has two consequences:
            1) All cached test results will be invalidated if any requirement in the lockfile
               changes, rather than just those that depend on the changed requirement.
            2) Requirements unneeded by a test/run/repl will be present on the sys.path, which
               might in rare cases cause their behavior to change.

            This option does not affect packaging deployable artifacts, such as
            PEX files, wheels and cloud functions, which will still use just the exact
            subset of requirements needed.
            """
        ),
        advanced=True,
    )

    __constraints_deprecation_msg = softwrap(
        f"""
        We encourage instead migrating to `[python].enable_resolves` and `[python].resolves`,
        which is an improvement over this option. The `[python].resolves` feature ensures that
        your lockfiles are fully comprehensive, i.e. include all transitive dependencies;
        uses hashes for better supply chain security; and supports advanced features like VCS
        and local requirements, along with options `[python].resolves_to_only_binary`.

        To migrate, stop setting `[python].requirement_constraints` and
        `[python].resolve_all_constraints`, and instead set `[python].enable_resolves` to
        `true`. Then, run `{bin_name()} generate-lockfiles`.
        """
    )
    requirement_constraints = FileOption(
        default=None,
        help=softwrap(
            """
            When resolving third-party requirements for your own code (vs. tools you run),
            use this constraints file to determine which versions to use.

            Mutually exclusive with `[python].enable_resolves`, which we generally recommend as an
            improvement over constraints file.

            See https://pip.pypa.io/en/stable/user_guide/#constraints-files for more
            information on the format of constraint files and how constraints are applied in
            Pex and pip.

            This only applies when resolving user requirements, rather than tools you run
            like Black and Pytest. To constrain tools, set `[tool].lockfile`, e.g.
            `[black].lockfile`.
            """
        ),
        advanced=True,
        mutually_exclusive_group="lockfile",
        removal_version="3.0.0.dev0",
        removal_hint=__constraints_deprecation_msg,
    )
    _resolve_all_constraints = BoolOption(
        default=True,
        help=softwrap(
            """
            (Only relevant when using `[python].requirement_constraints.`) If enabled, when
            resolving requirements, Pants will first resolve your entire
            constraints file as a single global resolve. Then, if the code uses a subset of
            your constraints file, Pants will extract the relevant requirements from that
            global resolve so that only what's actually needed gets used. If disabled, Pants
            will not use a global resolve and will resolve each subset of your requirements
            independently.

            Usually this option should be enabled because it can result in far fewer resolves.
            """
        ),
        advanced=True,
        removal_version="3.0.0.dev0",
        removal_hint=__constraints_deprecation_msg,
    )
    resolver_manylinux = StrOption(
        default="manylinux2014",
        help=softwrap(
            """
            Whether to allow resolution of manylinux wheels when resolving requirements for
            foreign linux platforms. The value should be a manylinux platform upper bound,
            e.g. `'manylinux2010'`, or else the string `'no'` to disallow.
            """
        ),
        advanced=True,
    )

    tailor_source_targets = BoolOption(
        default=True,
        help=softwrap(
            """
            If true, add `python_sources`, `python_tests`, and `python_test_utils` targets with
            the `tailor` goal."""
        ),
        advanced=True,
    )
    tailor_ignore_empty_init_files = BoolOption(
        "--tailor-ignore-empty-init-files",
        default=True,
        help=softwrap(
            """
            If true, don't add `python_sources` targets for `__init__.py` files that are both empty
            and where there are no other Python files in the directory.

            Empty and solitary `__init__.py` files usually exist as import scaffolding rather than
            true library code, so it can be noisy to add BUILD files.

            Even if this option is set to true, Pants will still ensure the empty `__init__.py`
            files are included in the sandbox when running processes.

            If you set to false, you may also want to set `[python-infer].init_files = "always"`.
            """
        ),
        advanced=True,
    )
    tailor_requirements_targets = BoolOption(
        default=True,
        help=softwrap(
            """
            If true, add `python_requirements`, `poetry_requirements`, and `pipenv_requirements`
            target generators with the `tailor` goal.

            `python_requirements` targets are added for any file that matches the pattern
            `*requirements*.txt`. You will need to manually add `python_requirements` for different
            file names like `reqs.txt`.

            `poetry_requirements` targets are added for `pyproject.toml` files with `[tool.poetry`
            in them.
            """
        ),
        advanced=True,
    )
    tailor_pex_binary_targets = BoolOption(
        default=False,
        help=softwrap(
            """
            If true, add `pex_binary` targets for Python files named `__main__.py` or with a
            `__main__` clause with the `tailor` goal.
            """
        ),
        advanced=True,
    )
    tailor_py_typed_targets = BoolOption(
        default=True,
        help=softwrap(
            """
            If true, add `resource` targets for marker files named `py.typed` with the `tailor` goal.
            """
        ),
        advanced=True,
    )
    macos_big_sur_compatibility = BoolOption(
        default=False,
        help=softwrap(
            """
            If set, and if running on macOS Big Sur, use `macosx_10_16` as the platform
            when building wheels. Otherwise, the default of `macosx_11_0` will be used.
            This may be required for `pip` to be able to install the resulting distribution
            on Big Sur.
            """
        ),
        advanced=True,
    )
    enable_lockfile_targets = BoolOption(
        default=True,
        help=softwrap(
            """
            Create targets for all Python lockfiles defined in `[python].resolves`.

            The lockfile targets will then be used as dependencies to the `python_requirement`
            targets that use them, invalidating source targets per resolve when the lockfile
            changes.

            If another targets address is in conflict with the created lockfile target, it will
            shadow the lockfile target and it will not be available as a dependency for any
            `python_requirement` targets.
            """
        ),
        advanced=True,
    )
    repl_history = BoolOption(
        default=True,
        help="Whether to use the standard Python command history file when running a repl.",
    )

    @property
    def enable_synthetic_lockfiles(self) -> bool:
        return self.enable_resolves and self.enable_lockfile_targets

    @memoized_property
    def resolves_to_interpreter_constraints(self) -> dict[str, tuple[str, ...]]:
        result = {}
        unrecognized_resolves = []
        for resolve, ics in self._resolves_to_interpreter_constraints.items():
            if resolve not in self.resolves:
                unrecognized_resolves.append(resolve)
            result[resolve] = tuple(ics)
        if unrecognized_resolves:
            raise UnrecognizedResolveNamesError(
                unrecognized_resolves,
                self.resolves.keys(),
                description_of_origin="the option `[python].resolves_to_interpreter_constraints`",
            )
        return result

    def _resolves_to_option_helper(
        self,
        option_value: dict[str, _T],
        option_name: str,
    ) -> dict[str, _T]:
        all_valid_resolves = set(self.resolves)
        unrecognized_resolves = set(option_value.keys()) - {
            RESOLVE_OPTION_KEY__DEFAULT,
            *all_valid_resolves,
        }
        if unrecognized_resolves:
            raise UnrecognizedResolveNamesError(
                sorted(unrecognized_resolves),
                {*all_valid_resolves, RESOLVE_OPTION_KEY__DEFAULT},
                description_of_origin=f"the option `[python].{option_name}`",
            )
        default_val = option_value.get(RESOLVE_OPTION_KEY__DEFAULT)
        if not default_val:
            return option_value
        return {resolve: option_value.get(resolve, default_val) for resolve in all_valid_resolves}

    @memoized_method
    def resolves_to_constraints_file(self) -> dict[str, str]:
        return self._resolves_to_option_helper(
            self._resolves_to_constraints_file,
            "resolves_to_constraints_file",
        )

    @memoized_method
    def resolves_to_no_binary(self) -> dict[str, list[str]]:
        return {
            resolve: [canonicalize_name(v) for v in vals]
            for resolve, vals in self._resolves_to_option_helper(
                self._resolves_to_no_binary,
                "resolves_to_no_binary",
            ).items()
        }

    @memoized_method
    def resolves_to_only_binary(self) -> dict[str, list[str]]:
        return {
            resolve: sorted([canonicalize_name(v) for v in vals])
            for resolve, vals in self._resolves_to_option_helper(
                self._resolves_to_only_binary,
                "resolves_to_only_binary",
            ).items()
        }

    @property
    def manylinux(self) -> str | None:
        manylinux = cast(Optional[str], self.resolver_manylinux)
        if manylinux is None or manylinux.lower() in ("false", "no", "none"):
            return None
        return manylinux

    @property
    def resolve_all_constraints(self) -> bool:
        if (
            self._resolve_all_constraints
            and not self.options.is_default("resolve_all_constraints")
            and not self.requirement_constraints
        ):
            raise ValueError(
                softwrap(
                    """
                    `[python].resolve_all_constraints` is enabled, so
                    `[python].requirement_constraints` must also be set.
                    """
                )
            )
        return self._resolve_all_constraints

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
