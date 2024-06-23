# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import importlib.resources
import json
import logging
import os
from dataclasses import dataclass
from functools import cache
from typing import Callable, ClassVar, Iterable, Optional, Sequence
from urllib.parse import urlparse

from pants.backend.python.target_types import ConsoleScript, EntryPoint, MainSpecification
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.lockfile_metadata import PythonLockfileMetadata
from pants.backend.python.util_rules.pex import PexRequest
from pants.backend.python.util_rules.pex_requirements import (
    EntireLockfile,
    LoadedLockfile,
    LoadedLockfileRequest,
    Lockfile,
    PexRequirements,
    Resolve,
    strip_comments_from_pex_json_lockfile,
)
from pants.core.goals.resolves import ExportableTool
from pants.engine.fs import Digest
from pants.engine.internals.selectors import Get
from pants.option.errors import OptionsError
from pants.option.option_types import StrListOption, StrOption
from pants.option.subsystem import Subsystem
from pants.util.docutil import doc_url, git_url
from pants.util.meta import classproperty
from pants.util.pip_requirement import PipRequirement
from pants.util.strutil import softwrap, strval

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _PackageNameAndVersion:
    name: str
    version: str


class PythonToolRequirementsBase(Subsystem, ExportableTool):
    """Base class for subsystems that configure a set of requirements for a python tool."""

    # Subclasses must set.
    default_version: ClassVar[str]
    # Must be set by subclasses - will be used to set the help text in this class.
    help_short: ClassVar[str | Callable[[], str]]
    # Subclasses do not need to override.
    default_extra_requirements: ClassVar[Sequence[str]] = []

    # Subclasses may set to override the value computed from default_version and
    # default_extra_requirements.
    # The primary package used in the subsystem must always be the first requirement.
    # TODO: Once we get rid of those options, subclasses must set this to loose
    #  requirements that reflect any minimum capabilities Pants assumes about the tool.
    default_requirements: Sequence[str] = []

    default_interpreter_constraints: ClassVar[Sequence[str]] = ["CPython>=3.7,<4"]
    register_interpreter_constraints: ClassVar[bool] = False

    default_lockfile_resource: ClassVar[tuple[str, str] | None] = None

    @classmethod
    def _help_extended(cls) -> str:
        base_help = strval(cls.help_short)
        help_paragraphs = [base_help]
        package_and_version = cls._default_package_name_and_version()
        if package_and_version:
            new_paragraph = f"This version of Pants uses `{package_and_version.name}` version {package_and_version.version} by default. Use a dedicated lockfile and the `install_from_resolve` option to control this."
            help_paragraphs.append(new_paragraph)

        return "\n\n".join(help_paragraphs)

    help = classproperty(_help_extended)

    @classmethod
    def _install_from_resolve_help(cls) -> str:
        package_and_version = cls._default_package_name_and_version()
        version_clause = (
            f", which uses `{package_and_version.name}` version {package_and_version.version}"
            if package_and_version
            else ""
        )
        return softwrap(
            f"""\
            If specified, install the tool using the lockfile for this named resolve.

            This resolve must be defined in `[python].resolves`, as described in
            {doc_url("docs/python/overview/lockfiles#lockfiles-for-tools")}.

            The resolve's entire lockfile will be installed, unless specific requirements are
            listed via the `requirements` option, in which case only those requirements
            will be installed. This is useful if you don't want to invalidate the tool's
            outputs when the resolve incurs changes to unrelated requirements.

            If unspecified, and the `lockfile` option is unset, the tool will be installed
            using the default lockfile shipped with Pants{version_clause}.

            If unspecified, and the `lockfile` option is set, the tool will use the custom
            `{cls.options_scope}` "tool lockfile" generated from the `version` and
            `extra_requirements` options. But note that this mechanism is deprecated.
            """
        )

    install_from_resolve = StrOption(
        advanced=True,
        default=None,
        help=lambda cls: cls._install_from_resolve_help(),
    )

    requirements = StrListOption(
        advanced=True,
        help=lambda cls: softwrap(
            """\
            If `install_from_resolve` is specified, install these requirements,
            at the versions provided by the specified resolve's lockfile.

            Values can be pip-style requirements (e.g., `tool` or `tool==1.2.3` or `tool>=1.2.3`),
            or addresses of `python_requirement` targets (or targets that generate or depend on
            `python_requirement` targets).

            The lockfile will be validated against the requirements - if a lockfile doesn't
            provide the requirement (at a suitable version, if the requirement specifies version
            constraints) Pants will error.

            If unspecified, install the entire lockfile.
            """
        ),
    )
    _interpreter_constraints = StrListOption(
        register_if=lambda cls: cls.register_interpreter_constraints,
        advanced=True,
        default=lambda cls: cls.default_interpreter_constraints,
        help="Python interpreter constraints for this tool.",
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

    @classmethod
    def help_for_generate_lockfile_with_default_location(cls, resolve_name):
        return softwrap(
            f"""
            You requested to generate a lockfile for {resolve_name} because
            you included it in `--generate-lockfiles-resolve`, but
            {resolve_name} is a tool using its default lockfile.

            If you would like to generate a lockfile for {resolve_name},
            follow the instructions for setting up lockfiles for tools
            {doc_url('docs/python/overview/lockfiles#lockfiles-for-tools')}
        """
        )

    @classmethod
    def pex_requirements_for_default_lockfile(cls):
        """Generate the pex requirements using this subsystem's default lockfile resource."""
        assert cls.default_lockfile_resource is not None
        pkg, path = cls.default_lockfile_resource
        url = f"resource://{pkg}/{path}"
        origin = f"The built-in default lockfile for {cls.options_scope}"
        return Lockfile(
            url=url,
            url_description_of_origin=origin,
            resolve_name=cls.options_scope,
        )

    @classmethod
    @cache
    def _default_package_name_and_version(cls) -> Optional[_PackageNameAndVersion]:
        if cls.default_lockfile_resource is None:
            return None

        lockfile = cls.pex_requirements_for_default_lockfile()
        parts = urlparse(lockfile.url)
        # urlparse retains the leading / in URLs with a netloc.
        lockfile_path = parts.path[1:] if parts.path.startswith("/") else parts.path
        if parts.scheme in {"", "file"}:
            with open(lockfile_path, "rb") as fp:
                lock_bytes = fp.read()
        elif parts.scheme == "resource":
            # The "netloc" in our made-up "resource://" scheme is the package.
            lock_bytes = importlib.resources.read_binary(parts.netloc, lockfile_path)
        else:
            raise ValueError(
                f"Unsupported scheme {parts.scheme} for lockfile URL: {lockfile.url} "
                f"(origin: {lockfile.url_description_of_origin})"
            )

        stripped_lock_bytes = strip_comments_from_pex_json_lockfile(lock_bytes)
        lockfile_contents = json.loads(stripped_lock_bytes)
        # The first requirement must contain the primary package for this tool, otherwise
        # this will pick up the wrong requirement.
        first_default_requirement = PipRequirement.parse(cls.default_requirements[0])
        return next(
            _PackageNameAndVersion(
                name=first_default_requirement.project_name, version=requirement["version"]
            )
            for resolve in lockfile_contents["locked_resolves"]
            for requirement in resolve["locked_requirements"]
            if requirement["project_name"] == first_default_requirement.project_name
        )

    def pex_requirements(
        self,
        *,
        extra_requirements: Iterable[str] = (),
    ) -> PexRequirements | EntireLockfile:
        """The requirements to be used when installing the tool."""
        description_of_origin = f"the requirements of the `{self.options_scope}` tool"
        if self.install_from_resolve:
            use_entire_lockfile = not self.requirements
            return PexRequirements(
                (*self.requirements, *extra_requirements),
                from_superset=Resolve(self.install_from_resolve, use_entire_lockfile),
                description_of_origin=description_of_origin,
            )
        else:
            return EntireLockfile(self.pex_requirements_for_default_lockfile())

    @property
    def interpreter_constraints(self) -> InterpreterConstraints:
        """The interpreter constraints to use when installing and running the tool.

        This assumes you have set the class property `register_interpreter_constraints = True`.
        """
        return InterpreterConstraints(self._interpreter_constraints)

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


class PythonToolBase(PythonToolRequirementsBase):
    """Base class for subsystems that configure a python tool to be invoked out-of-process."""

    # Subclasses must set.
    default_main: ClassVar[MainSpecification]

    # Though possible, we do not recommend setting `default_main` to an Executable
    # instead of a ConsoleScript or an EntryPoint. Executable is a niche pex feature
    # designed to support poorly named executable python scripts that cannot be imported
    # (eg when a file has a character like "-" that is not valid in python identifiers).
    # As this should be rare or even non-existent, we do NOT add an `executable` option
    # to mirror the other MainSpecification options.

    console_script = StrOption(
        advanced=True,
        default=lambda cls: (
            cls.default_main.spec if isinstance(cls.default_main, ConsoleScript) else None
        ),
        help=softwrap(
            """
            The console script for the tool. Using this option is generally preferable to
            (and mutually exclusive with) specifying an `--entry-point` since console script
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
            tool does not offer a `--console-script` (which this option is mutually exclusive
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


async def get_loaded_lockfile(subsystem: PythonToolBase) -> LoadedLockfile:
    requirements = subsystem.pex_requirements()
    if isinstance(requirements, EntireLockfile):
        lockfile = requirements.lockfile
    else:
        assert isinstance(requirements, PexRequirements)
        assert isinstance(requirements.from_superset, Resolve)
        lockfile = await Get(Lockfile, Resolve, requirements.from_superset)
    loaded_lockfile = await Get(LoadedLockfile, LoadedLockfileRequest(lockfile))
    return loaded_lockfile


async def get_lockfile_metadata(subsystem: PythonToolBase) -> PythonLockfileMetadata:
    loaded_lockfile = await get_loaded_lockfile(subsystem)
    assert loaded_lockfile.metadata is not None
    return loaded_lockfile.metadata


async def get_lockfile_interpreter_constraints(
    subsystem: PythonToolBase,
) -> InterpreterConstraints:
    """If a lockfile is used, will try to find the interpreter constraints used to generate the
    lock.

    This allows us to work around https://github.com/pantsbuild/pants/issues/14912.
    """
    # If the tool's interpreter constraints are explicitly set, or it is not using a lockfile at
    # all, then we should use the tool's interpreter constraints option.
    if not subsystem.options.is_default("interpreter_constraints"):
        return subsystem.interpreter_constraints

    lockfile_metadata = await get_lockfile_metadata(subsystem)
    return lockfile_metadata.valid_for_interpreter_constraints
