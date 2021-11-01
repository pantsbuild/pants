# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import importlib.resources
from typing import ClassVar, Iterable, Sequence, cast

from pants.backend.python.target_types import ConsoleScript, EntryPoint, MainSpecification
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.lockfile_metadata import calculate_invalidation_digest
from pants.backend.python.util_rules.pex import (
    Lockfile,
    LockfileContent,
    PexRequirements,
    ToolCustomLockfile,
    ToolDefaultLockfile,
)
from pants.engine.fs import FileContent
from pants.option.errors import OptionsError
from pants.option.subsystem import Subsystem
from pants.util.ordered_set import FrozenOrderedSet

DEFAULT_TOOL_LOCKFILE = "<default>"
NO_TOOL_LOCKFILE = "<none>"


class PythonToolRequirementsBase(Subsystem):
    """Base class for subsystems that configure a set of requirements for a python tool."""

    # Subclasses must set.
    default_version: ClassVar[str]
    # Subclasses do not need to override.
    default_extra_requirements: ClassVar[Sequence[str]] = []

    default_interpreter_constraints: ClassVar[Sequence[str]] = []
    register_interpreter_constraints: ClassVar[bool] = False

    # If this tool does not mix with user requirements (e.g. Flake8 and Isort, but not Pylint and
    # Pytest), you should set this to True.
    #
    # You also need to subclass `PythonToolLockfileSentinel` and create a rule that goes from
    # it -> PythonToolLockfileRequest by calling `PythonLockFileRequest.from_python_tool()`.
    # Register the UnionRule.
    register_lockfile: ClassVar[bool] = False
    default_lockfile_resource: ClassVar[tuple[str, str] | None] = None
    default_lockfile_url: ClassVar[str | None] = None
    uses_requirements_from_source_plugins: ClassVar[bool] = False

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--version",
            type=str,
            advanced=True,
            default=cls.default_version,
            help="Requirement string for the tool.",
        )
        register(
            "--extra-requirements",
            type=list,
            member_type=str,
            advanced=True,
            default=cls.default_extra_requirements,
            help="Any additional requirement strings to use with the tool. This is useful if the "
            "tool allows you to install plugins or if you need to constrain a dependency to "
            "a certain version.",
        )

        if cls.default_interpreter_constraints and not cls.register_interpreter_constraints:
            raise ValueError(
                f"`default_interpreter_constraints` are configured for `{cls.options_scope}`, but "
                "`register_interpreter_constraints` is not set to `True`, so the "
                "`--interpreter-constraints` option will not be registered. Did you mean to set "
                "this?"
            )
        if cls.register_interpreter_constraints:
            register(
                "--interpreter-constraints",
                type=list,
                advanced=True,
                default=cls.default_interpreter_constraints,
                help="Python interpreter constraints for this tool.",
            )

        if cls.register_lockfile and (
            not cls.default_lockfile_resource or not cls.default_lockfile_url
        ):
            raise ValueError(
                "The class property `default_lockfile_resource` and `default_lockfile_url` "
                f"must be set if `register_lockfile` is set. See `{cls.options_scope}`."
            )
        if cls.register_lockfile:
            register(
                "--lockfile",
                type=str,
                default=DEFAULT_TOOL_LOCKFILE,
                advanced=True,
                help=(
                    "Path to a lockfile used for installing the tool.\n\n"
                    f"Set to the string `{DEFAULT_TOOL_LOCKFILE}` to use a lockfile provided by "
                    "Pants, so long as you have not changed the `--version` and "
                    "`--extra-requirements` options, and the tool's interpreter constraints are "
                    "compatible with the default. Pants will error or warn if the lockfile is not "
                    "compatible (controlled by `[python].invalid_lockfile_behavior`). See "
                    f"{cls.default_lockfile_url} for the default lockfile contents.\n\n"
                    f"Set to the string `{NO_TOOL_LOCKFILE}` to opt out of using a lockfile. We "
                    f"do not recommend this, though, as lockfiles are essential for reproducible "
                    f"builds.\n\n"
                    "To use a custom lockfile, set this option to a file path relative to the "
                    f"build root, then run `./pants generate-lockfiles "
                    f"--resolve={cls.options_scope}`.\n\n"
                    "Lockfile generation currently does not wire up the `[python-repos]` options. "
                    "If lockfile generation fails, you can manually generate a lockfile, such as "
                    "by using pip-compile or `pip freeze`. Set this option to the path to your "
                    "manually generated lockfile. When manually maintaining lockfiles, set "
                    "`[python].invalid_lockfile_behavior = 'ignore'`."
                ),
            )

    @property
    def version(self) -> str:
        return cast(str, self.options.version)

    @property
    def extra_requirements(self) -> tuple[str, ...]:
        return tuple(self.options.extra_requirements)

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
    ) -> PexRequirements | Lockfile | LockfileContent:
        """The requirements to be used when installing the tool.

        If the tool supports lockfiles, the returned type will install from the lockfile rather than
        `all_requirements`.
        """

        requirements = (*self.all_requirements, *extra_requirements)

        if not self.uses_lockfile:
            return PexRequirements(requirements)

        hex_digest = calculate_invalidation_digest(requirements)

        if self.lockfile == DEFAULT_TOOL_LOCKFILE:
            assert self.default_lockfile_resource is not None
            return ToolDefaultLockfile(
                file_content=FileContent(
                    f"{self.options_scope}_default_lockfile.txt",
                    importlib.resources.read_binary(*self.default_lockfile_resource),
                ),
                lockfile_hex_digest=hex_digest,
                req_strings=FrozenOrderedSet(requirements),
                options_scope_name=self.options_scope,
                uses_project_interpreter_constraints=(not self.register_interpreter_constraints),
                uses_source_plugins=self.uses_requirements_from_source_plugins,
            )
        return ToolCustomLockfile(
            file_path=self.lockfile,
            file_path_description_of_origin=f"the option `[{self.options_scope}].lockfile`",
            lockfile_hex_digest=hex_digest,
            req_strings=FrozenOrderedSet(requirements),
            options_scope_name=self.options_scope,
            uses_project_interpreter_constraints=(not self.register_interpreter_constraints),
            uses_source_plugins=self.uses_requirements_from_source_plugins,
        )

    @property
    def lockfile(self) -> str:
        f"""The path to a lockfile or special strings '{NO_TOOL_LOCKFILE}' and '{DEFAULT_TOOL_LOCKFILE}'.

        This assumes you have set the class property `register_lockfile = True`.
        """
        return cast(str, self.options.lockfile)

    @property
    def uses_lockfile(self) -> bool:
        return self.register_lockfile and self.lockfile != NO_TOOL_LOCKFILE

    @property
    def interpreter_constraints(self) -> InterpreterConstraints:
        """The interpreter constraints to use when installing and running the tool.

        This assumes you have set the class property `register_interpreter_constraints = True`.
        """
        return InterpreterConstraints(self.options.interpreter_constraints)


class PythonToolBase(PythonToolRequirementsBase):
    """Base class for subsystems that configure a python tool to be invoked out-of-process."""

    # Subclasses must set.
    default_main: ClassVar[MainSpecification]

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--console-script",
            type=str,
            advanced=True,
            default=cls.default_main.spec if isinstance(cls.default_main, ConsoleScript) else None,
            help=(
                "The console script for the tool. Using this option is generally preferable to "
                "(and mutually exclusive with) specifying an --entry-point since console script "
                "names have a higher expectation of staying stable across releases of the tool. "
                "Usually, you will not want to change this from the default."
            ),
        )
        register(
            "--entry-point",
            type=str,
            advanced=True,
            default=cls.default_main.spec if isinstance(cls.default_main, EntryPoint) else None,
            help=(
                "The entry point for the tool. Generally you only want to use this option if the "
                "tool does not offer a --console-script (which this option is mutually exclusive "
                "with). Usually, you will not want to change this from the default."
            ),
        )

    @property
    def main(self) -> MainSpecification:
        is_default_console_script = self.options.is_default("console_script")
        is_default_entry_point = self.options.is_default("entry_point")
        if not is_default_console_script and not is_default_entry_point:
            raise OptionsError(
                f"Both [{self.options_scope}].console-script={self.options.console_script} and "
                f"[{self.options_scope}].entry-point={self.options.entry_point} are configured "
                f"but these options are mutually exclusive. Please pick one."
            )
        if not is_default_console_script:
            return ConsoleScript(cast(str, self.options.console_script))
        if not is_default_entry_point:
            return EntryPoint.parse(cast(str, self.options.entry_point))
        return self.default_main
