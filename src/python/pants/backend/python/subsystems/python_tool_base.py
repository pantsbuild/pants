# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
from typing import Any, ClassVar, Iterable, Sequence

from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.target_types import ConsoleScript, EntryPoint, MainSpecification
from pants.backend.python.util_rules import lockfile
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import PexRequest
from pants.backend.python.util_rules.pex_requirements import (
    EntireLockfile,
    LoadedLockfile,
    LoadedLockfileRequest,
    Lockfile,
    PexRequirements,
    Resolve,
)
from pants.core.goals.generate_lockfiles import DEFAULT_TOOL_LOCKFILE, NO_TOOL_LOCKFILE
from pants.core.util_rules.lockfile_metadata import calculate_invalidation_digest
from pants.engine.fs import Digest
from pants.engine.internals.selectors import Get
from pants.option.errors import OptionsError
from pants.option.option_types import BoolOption, StrListOption, StrOption
from pants.option.subsystem import Subsystem
from pants.util.docutil import bin_name, doc_url, git_url
from pants.util.memo import memoized_property
from pants.util.meta import classproperty
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


LockfileRules = lockfile.LockfileRules  # explicit re-export


class PythonToolRequirementsBase(Subsystem):
    """Base class for subsystems that configure a set of requirements for a python tool."""

    # Subclasses must set.
    default_version: ClassVar[str]
    # Subclasses do not need to override.
    default_extra_requirements: ClassVar[Sequence[str]] = []

    # Subclasses may set to override the value computed from default_version and
    # default_extra_requirements.
    # TODO: Once we get rid of those options, subclasses must set this to loose
    #  requirements that reflect any minimum capabilities Pants assumes about the tool.
    default_requirements: Sequence[str] = []

    default_interpreter_constraints: ClassVar[Sequence[str]] = ["CPython>=3.7,<4"]
    register_interpreter_constraints: ClassVar[bool] = False

    default_lockfile_resource: ClassVar[tuple[str, str] | None] = None
    lockfile_rules_type: LockfileRules = LockfileRules.CUSTOM

    install_from_resolve = StrOption(
        advanced=True,
        default=None,
        help=lambda cls: softwrap(
            f"""\
            If specified, install the tool using the lockfile for this named resolve.

            This resolve must be defined in [python].resolves, as described in
            {doc_url("python-third-party-dependencies#user-lockfiles")}.

            The resolve's entire lockfile will be installed, unless specific requirements are
            listed via the `requirements` option, in which case only those requirements
            will be installed. This is useful if you don't want to invalidate the tool's
            outputs when the resolve incurs changes to unrelated requirements.

            If unspecified, and the `lockfile` option is unset, the tool will be installed
            using the default lockfile shipped with Pants.

            If unspecified, and the `lockfile` option is set, the tool will use the custom
            `{cls.options_scope}` "tool lockfile" generated from the `version` and
            `extra_requirements` options. But note that this mechanism is deprecated.
            """
        ),
    )

    requirements = StrListOption(
        advanced=True,
        help=lambda cls: softwrap(
            """\
            If install_from_resolve is specified, install these requirements,
            at the versions provided by the specified resolve's lockfile.

            Values can be pip-style requirements (e.g., `tool` or `tool==1.2.3` or `tool>=1.2.3`),
            or addresses of python_requirement targets (or targets that generate or depend on
            python_requirement targets).

            The lockfile will be validated against the requirements - if a lockfile doesn't
            provide the requirement (at a suitable version, if the requirement specifies version
            constraints) Pants will error.

            If unspecified, install the entire lockfile.
            """
        ),
    )
    version = StrOption(
        advanced=True,
        default=lambda cls: cls.default_version,
        removal_version="2.18.0.dev1",
        removal_hint=lambda cls: softwrap(
            f"""\
            Custom tool versions are now installed from named resolves, as
            described at {doc_url("python-lockfiles")}.
            """
        ),
        help="Requirement string for the tool.",
    )
    extra_requirements = StrListOption(
        advanced=True,
        default=lambda cls: cls.default_extra_requirements,
        removal_version="2.18.0.dev1",
        removal_hint=lambda cls: softwrap(
            f"""\
            Custom tool versions are now installed from named resolves, as
            described at {doc_url("python-lockfiles")}.
            """
        ),
        help="Any additional requirement strings to use with the tool. This is useful if the "
        "tool allows you to install plugins or if you need to constrain a dependency to "
        "a certain version.",
    )
    _interpreter_constraints = StrListOption(
        register_if=lambda cls: cls.register_interpreter_constraints,
        advanced=True,
        default=lambda cls: cls.default_interpreter_constraints,
        help="Python interpreter constraints for this tool.",
    )

    _lockfile = StrOption(
        default=DEFAULT_TOOL_LOCKFILE,
        advanced=True,
        removal_version="2.18.0.dev0",
        removal_hint=lambda cls: softwrap(
            f"""\
            Custom tool versions are now installed from named resolves, as
            described at {doc_url("python-lockfiles")}.

            1. If you have an existing resolve that includes the requirements for this tool,
                you can set `[{cls.options_scope}].install_from_resolve = "<resolve name>".
                This may be the case if the tool also provides a runtime library, and you want
                to specify the version in just one place.
            2. If not, you can set up a new resolve as described at the link above.

            Either way, the resolve you choose should provide the requirements currently set
            by the `version` and `extra-requirements` options for this tool, which you can see
            by running `pants help-advanced {cls.options_scope}`.
            """
        ),
        help=lambda cls: softwrap(
            f"""
            Path to a lockfile used for installing the tool.

            Set to the string `{DEFAULT_TOOL_LOCKFILE}` to use a lockfile provided by
            Pants, so long as you have not changed the `--version` and
            `--extra-requirements` options, and the tool's interpreter constraints are
            compatible with the default. Pants will error or warn if the lockfile is not
            compatible (controlled by `[python].invalid_lockfile_behavior`). See
            {cls.default_lockfile_url} for the default lockfile contents.

            To use a custom lockfile, set this option to a file path relative to the
            build root, then run `{bin_name()} generate-lockfiles --resolve={cls.options_scope}`.

            Alternatively, you can set this option to the path to a custom lockfile using pip's
            requirements.txt-style, ideally with `--hash`. Set
            `[python].invalid_lockfile_behavior = 'ignore'` so that Pants does not complain about
            missing lockfile headers.
            """
        ),
    )

    def __init__(self, *args, **kwargs):
        if (
            self.default_interpreter_constraints
            != PythonToolRequirementsBase.default_interpreter_constraints
            and not self.register_interpreter_constraints
        ):
            raise ValueError(
                softwrap(
                    f"""
                    `default_interpreter_constraints` are configured for `{self.options_scope}`, but
                    `register_interpreter_constraints` is not set to `True`, so the
                    `--interpreter-constraints` option will not be registered. Did you mean to set
                    this?
                    """
                )
            )

        if not self.default_lockfile_resource:
            raise ValueError(
                softwrap(
                    f"""
                    The class property `default_lockfile_resource` must be set. See `{self.options_scope}`.
                    """
                )
            )

        super().__init__(*args, **kwargs)

    @classproperty
    def default_lockfile_url(cls) -> str:
        assert cls.default_lockfile_resource is not None
        return git_url(
            os.path.join(
                "src",
                "python",
                cls.default_lockfile_resource[0].replace(".", os.path.sep),
                cls.default_lockfile_resource[1],
            )
        )

    @property
    def all_requirements(self) -> tuple[str, ...]:
        """All the raw requirement strings to install the tool.

        This may not include transitive dependencies: these are top-level requirements.
        """
        return (self.version, *self.extra_requirements)

    def pex_requirements(
        self,
        *,
        extra_requirements: Iterable[str] = (),
    ) -> PexRequirements | EntireLockfile:
        """The requirements to be used when installing the tool.

        If the tool supports lockfiles, the returned type will install from the lockfile rather than
        `all_requirements`.
        """
        description_of_origin = f"the requirements of the `{self.options_scope}` tool"
        if self.install_from_resolve:
            use_entire_lockfile = not self.requirements
            return PexRequirements(
                (*self.requirements, *extra_requirements),
                from_superset=Resolve(self.install_from_resolve, use_entire_lockfile),
                description_of_origin=description_of_origin,
            )

        requirements = (*self.all_requirements, *extra_requirements)

        if not self.uses_lockfile:
            return PexRequirements(requirements, description_of_origin=description_of_origin)

        hex_digest = calculate_invalidation_digest(requirements)

        if self.lockfile == DEFAULT_TOOL_LOCKFILE:
            assert self.default_lockfile_resource is not None
            pkg, path = self.default_lockfile_resource
            url = f"resource://{pkg}/{path}"
            origin = f"The built-in default lockfile for {self.options_scope}"
        else:
            url = self.lockfile
            origin = f"the option `[{self.options_scope}].lockfile`"

        lockfile = Lockfile(
            url=url,
            url_description_of_origin=origin,
            lockfile_hex_digest=hex_digest,
            resolve_name=self.options_scope,
        )
        return EntireLockfile(lockfile, complete_req_strings=tuple(requirements))

    @memoized_property
    def lockfile(self) -> str:
        f"""The path to a lockfile.

        Or one of the special strings '{NO_TOOL_LOCKFILE}' or '{DEFAULT_TOOL_LOCKFILE}'.
        """
        if self._lockfile not in {NO_TOOL_LOCKFILE, DEFAULT_TOOL_LOCKFILE}:
            # Augment the deprecation message for the option with useful information
            # about the remedy. We will only display this note if the invocation actually
            # tries to use the tool, whereas the deprecations will display on options parsing,
            # so this is just a best-effort attempt to be helpful when we can.
            tool_reqs = [self.version, *self.extra_requirements]
            logger.warning(
                f"Note: the resolve you use for the {self.options_scope} tool must "
                f"provide these requirements:" + "\n\n" + "\n".join(tool_reqs) + "\n"
            )
        return self._lockfile

    @property
    def uses_lockfile(self) -> bool:
        """Return true if the tool is installed from an old-style tool lockfile.

        Note that this lockfile may be the default lockfile Pants distributes.
        """
        return self.lockfile != NO_TOOL_LOCKFILE

    @property
    def uses_custom_lockfile(self) -> bool:
        """Return true if the tool is installed from an old-style custom lockfile."""
        return self.lockfile not in (
            NO_TOOL_LOCKFILE,
            DEFAULT_TOOL_LOCKFILE,
        )

    @property
    def interpreter_constraints(self) -> InterpreterConstraints:
        """The interpreter constraints to use when installing and running the tool.

        This assumes you have set the class property `register_interpreter_constraints = True`.
        """
        return InterpreterConstraints(self._interpreter_constraints)

    def to_lockfile_request(
        self,
        interpreter_constraints: InterpreterConstraints | None = None,
        extra_requirements: Iterable[str] = (),
    ) -> GeneratePythonLockfile:
        """Create a request for a dedicated lockfile for the tool.

        If the tool determines its interpreter constraints by using the constraints of user code,
        rather than the option `--interpreter-constraints`, you must pass the arg
        `interpreter_constraints`.
        """
        if not self.uses_custom_lockfile:
            return GeneratePythonLockfile(
                requirements=FrozenOrderedSet(),
                interpreter_constraints=InterpreterConstraints(),
                resolve_name=self.options_scope,
                lockfile_dest=self.lockfile,
                diff=False,
            )
        return GeneratePythonLockfile(
            requirements=FrozenOrderedSet((*self.all_requirements, *extra_requirements)),
            interpreter_constraints=(
                interpreter_constraints
                if interpreter_constraints is not None
                else self.interpreter_constraints
            ),
            resolve_name=self.options_scope,
            lockfile_dest=self.lockfile,
            diff=False,
        )

    def to_pex_request(
        self,
        *,
        interpreter_constraints: InterpreterConstraints | None = None,
        extra_requirements: Iterable[str] = (),
        main: MainSpecification | None = None,
        sources: Digest | None = None,
    ) -> PexRequest:
        requirements = self.pex_requirements(extra_requirements=extra_requirements)
        if not interpreter_constraints:
            if self.options.is_default("interpreter_constraints") and (
                isinstance(requirements, EntireLockfile)
                or (
                    isinstance(requirements, PexRequirements)
                    and isinstance(requirements.from_superset, Resolve)
                )
            ):
                # If installing the tool from a resolve, and custom ICs weren't explicitly set,
                # leave these blank. This will cause the ones for the resolve to be used,
                # which is clearly what the user intends, rather than forcing the
                # user to override interpreter_constraints to match those of the resolve.
                interpreter_constraints = InterpreterConstraints()
            else:
                interpreter_constraints = self.interpreter_constraints
        return PexRequest(
            output_filename=f"{self.options_scope.replace('-', '_')}.pex",
            internal_only=True,
            requirements=requirements,
            interpreter_constraints=interpreter_constraints,
            main=main,
            sources=sources,
        )

    @classmethod
    def rules(cls: Any) -> Iterable[Any]:
        yield from super().rules()

        yield from lockfile.default_rules(cls)


class PythonToolBase(PythonToolRequirementsBase):
    """Base class for subsystems that configure a python tool to be invoked out-of-process."""

    # Subclasses must set.
    default_main: ClassVar[MainSpecification]

    console_script = StrOption(
        advanced=True,
        default=lambda cls: (
            cls.default_main.spec if isinstance(cls.default_main, ConsoleScript) else None
        ),
        help=softwrap(
            """
            The console script for the tool. Using this option is generally preferable to
            (and mutually exclusive with) specifying an --entry-point since console script
            names have a higher expectation of staying stable across releases of the tool.
            Usually, you will not want to change this from the default.
            """
        ),
    )
    entry_point = StrOption(
        advanced=True,
        default=lambda cls: (
            cls.default_main.spec if isinstance(cls.default_main, EntryPoint) else None
        ),
        help=softwrap(
            """
            The entry point for the tool. Generally you only want to use this option if the
            tool does not offer a --console-script (which this option is mutually exclusive
            with). Usually, you will not want to change this from the default.
            """
        ),
    )

    @property
    def main(self) -> MainSpecification:
        is_default_console_script = self.options.is_default("console_script")
        is_default_entry_point = self.options.is_default("entry_point")
        if not is_default_console_script and not is_default_entry_point:
            raise OptionsError(
                softwrap(
                    f"""
                    Both [{self.options_scope}].console-script={self.console_script} and
                    [{self.options_scope}].entry-point={self.entry_point} are configured
                    but these options are mutually exclusive. Please pick one.
                    """
                )
            )
        if not is_default_console_script:
            assert self.console_script is not None
            return ConsoleScript(self.console_script)
        if not is_default_entry_point:
            assert self.entry_point is not None
            return EntryPoint.parse(self.entry_point)
        return self.default_main

    def to_pex_request(
        self,
        *,
        interpreter_constraints: InterpreterConstraints | None = None,
        extra_requirements: Iterable[str] = (),
        main: MainSpecification | None = None,
        sources: Digest | None = None,
    ) -> PexRequest:
        return super().to_pex_request(
            interpreter_constraints=interpreter_constraints,
            extra_requirements=extra_requirements,
            main=main or self.main,
            sources=sources,
        )

    @staticmethod
    async def _find_python_interpreter_constraints_from_lockfile(
        subsystem: PythonToolBase,
    ) -> InterpreterConstraints:
        """If a lockfile is used, will try to find the interpreter constraints used to generate the
        lock.

        This allows us to work around https://github.com/pantsbuild/pants/issues/14912.
        """
        # If the tool's interpreter constraints are explicitly set, or it is not using a lockfile at
        # all, then we should use the tool's interpreter constraints option.
        if (
            not subsystem.options.is_default("interpreter_constraints")
            or not subsystem.uses_lockfile
        ):
            return subsystem.interpreter_constraints

        # If using Pants's default lockfile, we can simply use the tool's default interpreter
        # constraints, which we trust were used to generate Pants's default tool lockfile.
        if not subsystem.uses_custom_lockfile:
            return InterpreterConstraints(subsystem.default_interpreter_constraints)

        # Else, try to load the metadata block from the lockfile.
        requirements = subsystem.pex_requirements()
        assert isinstance(requirements, EntireLockfile)
        lockfile = await Get(LoadedLockfile, LoadedLockfileRequest(requirements.lockfile))
        return (
            lockfile.metadata.valid_for_interpreter_constraints
            if lockfile.metadata
            else subsystem.interpreter_constraints
        )


class ExportToolOption(BoolOption):
    """An `--export` option to toggle whether the `export` goal should include the tool."""

    def __new__(cls):
        return super().__new__(
            cls,
            default=True,
            removal_version="2.18.0.dev0",
            removal_hint="Use the export goal's --resolve option to select tools to export, instead "
            "of using this option to exempt a tool from export-by-default.",
            help=(
                lambda subsystem_cls: softwrap(
                    f"""
                    If true, export a virtual environment with {subsystem_cls.name} when running
                    `{bin_name()} export`.

                    This can be useful, for example, with IDE integrations to point your editor to
                    the tool's binary.
                    """
                )
            ),
        )
