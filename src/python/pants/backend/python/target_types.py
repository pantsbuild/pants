# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import collections.abc
import logging
import os.path
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import (
    TYPE_CHECKING,
    ClassVar,
    Iterable,
    Iterator,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
    cast,
)

from packaging.utils import canonicalize_name as canonicalize_project_name

from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.subsystems.setup import PythonSetup
from pants.core.goals.generate_lockfiles import UnrecognizedResolveNamesError
from pants.core.goals.package import OutputPathField
from pants.core.goals.run import RestartableField
from pants.core.goals.test import (
    RuntimePackageDependenciesField,
    TestExtraEnvVarsField,
    TestsBatchCompatibilityTagField,
    TestSubsystem,
)
from pants.core.util_rules.environments import EnvironmentField
from pants.engine.addresses import Address, Addresses
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AsyncFieldMixin,
    BoolField,
    Dependencies,
    DictStringToStringField,
    DictStringToStringSequenceField,
    Field,
    IntField,
    InvalidFieldException,
    InvalidFieldTypeException,
    InvalidTargetException,
    MultipleSourcesField,
    NestedDictStringToStringField,
    OptionalSingleSourceField,
    OverridesField,
    ScalarField,
    SingleSourceField,
    SpecialCasedDependencies,
    StringField,
    StringSequenceField,
    Target,
    TargetFilesGenerator,
    TargetFilesGeneratorSettingsRequest,
    TargetGenerator,
    TriBoolField,
    ValidNumbers,
    generate_file_based_overrides_field_help_message,
    generate_multiple_sources_field_help_message,
)
from pants.option.option_types import BoolOption
from pants.option.subsystem import Subsystem
from pants.util.docutil import bin_name, doc_url, git_url
from pants.util.frozendict import FrozenDict
from pants.util.pip_requirement import PipRequirement
from pants.util.strutil import help_text, softwrap

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pants.backend.python.subsystems.pytest import PyTest


# -----------------------------------------------------------------------------------------------
# Common fields
# -----------------------------------------------------------------------------------------------


class PythonSourceField(SingleSourceField):
    # Note that Python scripts often have no file ending.
    expected_file_extensions: ClassVar[tuple[str, ...]] = ("", ".py", ".pyi")


class PythonDependenciesField(Dependencies):
    pass


class PythonGeneratingSourcesBase(MultipleSourcesField):
    expected_file_extensions: ClassVar[tuple[str, ...]] = ("", ".py", ".pyi")


class InterpreterConstraintsField(StringSequenceField):
    alias = "interpreter_constraints"
    help = help_text(
        f"""
        The Python interpreters this code is compatible with.

        Each element should be written in pip-style format, e.g. `CPython==2.7.*` or
        `CPython>=3.6,<4`. You can leave off `CPython` as a shorthand, e.g. `>=2.7` will be expanded
        to `CPython>=2.7`.

        Specify more than one element to OR the constraints, e.g. `['PyPy==3.7.*', 'CPython==3.7.*']`
        means either PyPy 3.7 _or_ CPython 3.7.

        If the field is not set, it will default to the option `[python].interpreter_constraints`.

        See {doc_url('python-interpreter-compatibility')} for how these interpreter
        constraints are merged with the constraints of dependencies.
        """
    )

    def value_or_global_default(self, python_setup: PythonSetup) -> Tuple[str, ...]:
        """Return either the given `compatibility` field or the global interpreter constraints.

        If interpreter constraints are supplied by the CLI flag, return those only.
        """
        return python_setup.compatibility_or_constraints(self.value)


class PythonResolveField(StringField, AsyncFieldMixin):
    alias = "resolve"
    required = False
    help = help_text(
        """
        The resolve from `[python].resolves` to use.

        If not defined, will default to `[python].default_resolve`.

        All dependencies must share the same value for their `resolve` field.
        """
    )

    def normalized_value(self, python_setup: PythonSetup) -> str:
        """Get the value after applying the default and validating that the key is recognized."""
        if not python_setup.enable_resolves:
            return "<ignore>"
        resolve = self.value or python_setup.default_resolve
        if resolve not in python_setup.resolves:
            raise UnrecognizedResolveNamesError(
                [resolve],
                python_setup.resolves.keys(),
                description_of_origin=f"the field `{self.alias}` in the target {self.address}",
            )
        return resolve


class PythonRunGoalUseSandboxField(TriBoolField):
    alias = "run_goal_use_sandbox"
    help = help_text(
        """
        Whether to use a sandbox when `run`ning this target. Defaults to `[python].run_goal_use_sandbox`.

        If true, runs of this target with the `run` goal will copy the needed first-party sources
        into a temporary sandbox and run from there.

        If false, runs of this target with the `run` goal will use the in-repo sources
        directly.

        Note that this field only applies when running a target with the `run` goal. No other goals
        (such as `test`, if applicable) consult this field.

        The former mode is more hermetic, and is closer to building and running the source as it
        were packaged in a `pex_binary`. Additionally, it may be necessary if your sources depend
        transitively on "generated" files which will be materialized in the sandbox in a source
        root, but are not in-repo.

        The latter mode is similar to creating, activating, and using a virtual environment when
        running your files. It may also be necessary if the source being run writes files into the
        repo and computes their location relative to the executed files. Django's `makemigrations`
        command is an example of such a process.
        """
    )


# -----------------------------------------------------------------------------------------------
# Target generation support
# -----------------------------------------------------------------------------------------------


class PythonFilesGeneratorSettingsRequest(TargetFilesGeneratorSettingsRequest):
    pass


# -----------------------------------------------------------------------------------------------
# `pex_binary` and `pex_binaries` target
# -----------------------------------------------------------------------------------------------


# See `target_types_rules.py` for a dependency injection rule.
class PexBinaryDependenciesField(Dependencies):
    supports_transitive_excludes = True


class MainSpecification(ABC):
    @abstractmethod
    def iter_pex_args(self) -> Iterator[str]:
        ...

    @property
    @abstractmethod
    def spec(self) -> str:
        ...


@dataclass(frozen=True)
class EntryPoint(MainSpecification):
    module: str
    function: str | None = None

    @classmethod
    def parse(cls, value: str, provenance: str | None = None) -> EntryPoint:
        given = f"entry point {provenance}" if provenance else "entry point"
        entry_point = value.strip()
        if not entry_point:
            raise ValueError(
                softwrap(
                    f"""
                    The {given} cannot be blank. It must indicate a Python module by name or path
                    and an optional nullary function in that module separated by a colon, i.e.:
                    module_name_or_path(':'function_name)?
                    """
                )
            )
        module_or_path, sep, func = entry_point.partition(":")
        if not module_or_path:
            raise ValueError(f"The {given} must specify a module; given: {value!r}")
        if ":" in func:
            raise ValueError(
                softwrap(
                    f"""
                    The {given} can only contain one colon separating the entry point's module from
                    the entry point function in that module; given: {value!r}
                    """
                )
            )
        if sep and not func:
            logger.warning(
                softwrap(
                    f"""
                    Assuming no entry point function and stripping trailing ':' from the {given}:
                    {value!r}. Consider deleting it to make it clear no entry point function is
                    intended.
                    """
                )
            )
        return cls(module=module_or_path, function=func if func else None)

    def __post_init__(self):
        if ":" in self.module:
            raise ValueError(
                softwrap(
                    f"""
                    The `:` character is not valid in a module name. Given an entry point module of
                    {self.module}. Did you mean to use EntryPoint.parse?
                    """
                )
            )
        if self.function and ":" in self.function:
            raise ValueError(
                softwrap(
                    f"""
                    The `:` character is not valid in a function name. Given an entry point function
                    of {self.function}.
                    """
                )
            )

    def iter_pex_args(self) -> Iterator[str]:
        yield "--entry-point"
        yield self.spec

    @property
    def spec(self) -> str:
        return self.module if self.function is None else f"{self.module}:{self.function}"


@dataclass(frozen=True)
class ConsoleScript(MainSpecification):
    name: str

    def iter_pex_args(self) -> Iterator[str]:
        yield "--console-script"
        yield self.name

    @property
    def spec(self) -> str:
        return self.name


@dataclass(frozen=True)
class Executable(MainSpecification):
    executable: str

    def iter_pex_args(self) -> Iterator[str]:
        yield "--executable"
        yield self.executable

    # TODO: does spec make sense here?
    @property
    def spec(self) -> str:
        return self.executable


class EntryPointField(AsyncFieldMixin, Field):
    alias = "entry_point"
    default = None
    help = help_text(
        """
        Set the entry point, i.e. what gets run when executing `./my_app.pex`, to a module.

        You can specify a full module like `'path.to.module'` and `'path.to.module:func'`, or use a
        shorthand to specify a file name, using the same syntax as the `sources` field:

          1) `'app.py'`, Pants will convert into the module `path.to.app`;
          2) `'app.py:func'`, Pants will convert into `path.to.app:func`.

        You may only set one of: this field, or the `script` field, or the `executable` field.
        Leave off all three fields to have no entry point.
        """
    )
    value: EntryPoint | None

    @classmethod
    def compute_value(cls, raw_value: Optional[str], address: Address) -> Optional[EntryPoint]:
        value = super().compute_value(raw_value, address)
        if value is None:
            return None
        if not isinstance(value, str):
            raise InvalidFieldTypeException(address, cls.alias, value, expected_type="a string")
        try:
            return EntryPoint.parse(value, provenance=f"for {address}")
        except ValueError as e:
            raise InvalidFieldException(str(e))


class PexEntryPointField(EntryPointField):
    # Specialist subclass for use with `PexBinary` targets.
    pass


# See `target_types_rules.py` for the `ResolvePexEntryPointRequest -> ResolvedPexEntryPoint` rule.
@dataclass(frozen=True)
class ResolvedPexEntryPoint:
    val: EntryPoint | None
    file_name_used: bool


@dataclass(frozen=True)
class ResolvePexEntryPointRequest:
    """Determine the `entry_point` for a `pex_binary` after applying all syntactic sugar."""

    entry_point_field: EntryPointField


class PexScriptField(Field):
    alias = "script"
    default = None
    help = help_text(
        """
        Set the entry point, i.e. what gets run when executing `./my_app.pex`, to a script or
        console_script as defined by any of the distributions in the PEX.

        You may only set one of: this field, or the `entry_point` field, or the `executable` field.
        Leave off all three fields to have no entry point.
        """
    )
    value: ConsoleScript | None

    @classmethod
    def compute_value(cls, raw_value: Optional[str], address: Address) -> Optional[ConsoleScript]:
        value = super().compute_value(raw_value, address)
        if value is None:
            return None
        if not isinstance(value, str):
            raise InvalidFieldTypeException(address, cls.alias, value, expected_type="a string")
        return ConsoleScript(value)


class PexExecutableField(Field):
    alias = "executable"
    default = None
    help = help_text(
        """
        Set the entry point, i.e. what gets run when executing `./my_app.pex`, to an execuatble
        local python script. This executable python script is typically something that cannot
        be imported so it cannot be used via `script` or `entry_point`.

        You may only set one of: this field, or the `entry_point` field, or the `script` field.
        Leave off all three fields to have no entry point.
        """
    )
    value: Executable | None

    @classmethod
    def compute_value(cls, raw_value: Optional[str], address: Address) -> Optional[Executable]:
        value = super().compute_value(raw_value, address)
        if value is None:
            return None
        if not isinstance(value, str):
            raise InvalidFieldTypeException(address, cls.alias, value, expected_type="a string")
        return Executable(value)


class PexArgsField(StringSequenceField):
    alias = "args"
    help = help_text(
        """
        Freeze these command-line args into the PEX. Allows you to run generic entry points
        on specific arguments without creating a shim file.
        """
    )


class PexEnvField(DictStringToStringField):
    alias = "env"
    help = help_text(
        """
        Freeze these environment variables into the PEX. Allows you to run generic entry points
        on a specific environment without creating a shim file.
        """
    )


class PexPlatformsField(StringSequenceField):
    alias = "platforms"
    removal_version = "2.22.0.dev0"
    removal_hint = softwrap(
        """\
    The platforms field is a hack. The abbreviated information it provides is sometimes insufficient,
    leading to hard-to-debug build issues. Use complete_platforms instead.
    See {doc_url('pex')} for details.
    """
    )
    help = help_text(
        """
        The abbreviated platforms the built PEX should be compatible with.

        There must be built wheels available for all of the foreign platforms, rather than sdists.

        You can give a list of multiple platforms to create a multiplatform PEX,
        meaning that the PEX will be executable in all of the supported environments.

        Platforms should be in the format defined by Pex
        (https://pex.readthedocs.io/en/latest/buildingpex.html#platform), i.e.
        PLATFORM-IMPL-PYVER-ABI (e.g. "linux_x86_64-cp-37-cp37m",
        "macosx_10.12_x86_64-cp-310-cp310"):

          - PLATFORM: the host platform, e.g. "linux-x86_64", "macosx-10.12-x86_64".
          - IMPL: the Python implementation abbreviation, e.g. "cp" or "pp".
          - PYVER: a two or more digit string representing the python major/minor version\
            (e.g., "37" or "310") or else a component dotted version string (e.g., "3.7" or "3.10.1").
          - ABI: the ABI tag, e.g. "cp37m", "cp310", "abi3", "none".

        Note that using an abbreviated platform means that certain resolves will fail when they
        encounter environment markers that cannot be deduced from the abbreviated platform
        string. A common example of this is 'python_full_version' which requires knowing the
        patch level version of the foreign Python interpreter. To remedy this you should use a
        3-component dotted version for PYVER. If your resolves fail due to more esoteric
        undefined environment markers, you should switch to specifying `complete_platforms`
        instead.
        """
    )


class PexCompletePlatformsField(SpecialCasedDependencies):
    alias = "complete_platforms"
    help = help_text(
        f"""
        The platforms the built PEX should be compatible with.

        There must be built wheels available for all of the foreign platforms, rather than sdists.

        You can give a list of multiple complete platforms to create a multiplatform PEX,
        meaning that the PEX will be executable in all of the supported environments.

        Complete platforms should be addresses of `file` targets that point to files that contain
        complete platform JSON as described by Pex
        (https://pex.readthedocs.io/en/latest/buildingpex.html#complete-platform).

        See {doc_url('pex')} for details.
        """
    )


class PexInheritPathField(StringField):
    alias = "inherit_path"
    valid_choices = ("false", "fallback", "prefer")
    help = help_text(
        """
        Whether to inherit the `sys.path` (aka PYTHONPATH) of the environment that the binary runs in.

        Use `false` to not inherit `sys.path`; use `fallback` to inherit `sys.path` after packaged
        dependencies; and use `prefer` to inherit `sys.path` before packaged dependencies.
        """
    )

    # TODO(#9388): deprecate allowing this to be a `bool`.
    @classmethod
    def compute_value(
        cls, raw_value: Optional[Union[str, bool]], address: Address
    ) -> Optional[str]:
        if isinstance(raw_value, bool):
            return "prefer" if raw_value else "false"
        return super().compute_value(raw_value, address)


class PexStripEnvField(BoolField):
    alias = "strip_pex_env"
    default = True
    help = help_text(
        """
        Whether or not to strip the PEX runtime environment of `PEX*` environment variables.

        Most applications have no need for the `PEX*` environment variables that are used to
        control PEX startup; so these variables are scrubbed from the environment by Pex before
        transferring control to the application by default. This prevents any subprocesses that
        happen to execute other PEX files from inheriting these control knob values since most
        would be undesired; e.g.: PEX_MODULE or PEX_PATH.
        """
    )


class PexIgnoreErrorsField(BoolField):
    alias = "ignore_errors"
    default = False
    help = "Should PEX ignore errors when it cannot resolve dependencies?"


class PexShBootField(BoolField):
    alias = "sh_boot"
    default = False
    help = help_text(
        """
        Should PEX create a modified ZIPAPP that uses `/bin/sh` to boot?

        If you know the machines that the PEX will be distributed to have
        POSIX compliant `/bin/sh` (almost all do, see:
        https://pubs.opengroup.org/onlinepubs/9699919799/utilities/sh.html);
        then this is probably the way you want your PEX to boot. Instead of
        launching via a Python shebang, the PEX will launch via a `#!/bin/sh`
        shebang that executes a small script embedded in the head of the PEX
        ZIPAPP that performs initial interpreter selection and re-execution of
        the underlying PEX in a way that is often more robust than a Python
        shebang and always faster on 2nd and subsequent runs since the sh
        script has a constant overhead of O(1ms) whereas the Python overhead
        to perform the same interpreter selection and re-execution is
        O(100ms).
        """
    )


class PexShebangField(StringField):
    alias = "shebang"
    help = help_text(
        """
        Set the generated PEX to use this shebang, rather than the default of PEX choosing a
        shebang based on the interpreter constraints.

        This influences the behavior of running `./result.pex`. You can ignore the shebang by
        instead running `/path/to/python_interpreter ./result.pex`.
        """
    )


class PexEmitWarningsField(TriBoolField):
    alias = "emit_warnings"
    help = help_text(
        """
        Whether or not to emit PEX warnings at runtime.

        The default is determined by the option `emit_warnings` in the `[pex-binary-defaults]` scope.
        """
    )

    def value_or_global_default(self, pex_binary_defaults: PexBinaryDefaults) -> bool:
        if self.value is None:
            return pex_binary_defaults.emit_warnings
        return self.value


class PexResolveLocalPlatformsField(TriBoolField):
    alias = "resolve_local_platforms"
    help = help_text(
        f"""
        For each of the `{PexPlatformsField.alias}` specified, attempt to find a local
        interpreter that matches.

        If a matching interpreter is found, use the interpreter to resolve distributions and build
        any that are only available in source distribution form.
        If no matching interpreter is found (or if this option is `False`), resolve for the
        platform by accepting only pre-built binary distributions (wheels).
        """
    )

    def value_or_global_default(self, pex_binary_defaults: PexBinaryDefaults) -> bool:
        if self.value is None:
            return pex_binary_defaults.resolve_local_platforms
        return self.value


class PexExecutionMode(Enum):
    ZIPAPP = "zipapp"
    VENV = "venv"


class PexExecutionModeField(StringField):
    alias = "execution_mode"
    valid_choices = PexExecutionMode
    expected_type = str
    default = PexExecutionMode.ZIPAPP.value
    help = help_text(
        f"""
        The mode the generated PEX file will run in.

        The traditional PEX file runs in a modified {PexExecutionMode.ZIPAPP.value!r} mode (See:
        https://www.python.org/dev/peps/pep-0441/) where zipped internal code and dependencies
        are first unpacked to disk. This mode achieves the fastest cold start times and may, for
        example be the best choice for cloud lambda functions.

        The fastest execution mode in the steady state is {PexExecutionMode.VENV.value!r}, which
        generates a virtual environment from the PEX file on first run, but then achieves near
        native virtual environment start times. This mode also benefits from a traditional virtual
        environment `sys.path`, giving maximum compatibility with stdlib and third party APIs.
        """
    )


class PexLayout(Enum):
    ZIPAPP = "zipapp"
    PACKED = "packed"
    LOOSE = "loose"


class PexLayoutField(StringField):
    alias = "layout"
    valid_choices = PexLayout
    expected_type = str
    default = PexLayout.ZIPAPP.value
    help = help_text(
        f"""
        The layout used for the PEX binary.

        By default, a PEX is created as a single file zipapp, but either a packed or loose directory
        tree based layout can be chosen instead.

        A packed layout PEX is an executable directory structure designed to have
        cache-friendly characteristics for syncing incremental updates to PEXed applications over
        a network. At the top level of the packed directory tree there is an executable
        `__main__.py` script. The directory can also be executed by passing its path to a Python
        executable; e.g: `python packed-pex-dir/`. The Pex bootstrap code and all dependency code
        are packed into individual zip files for efficient caching and syncing.

        A loose layout PEX is similar to a packed PEX, except that neither the Pex bootstrap code
        nor the dependency code are packed into zip files, but are instead present as collections of
        loose files in the directory tree providing different caching and syncing tradeoffs.

        Both zipapp and packed layouts install themselves in the `$PEX_ROOT` as loose apps by
        default before executing, but these layouts compose with
        `{PexExecutionModeField.alias}='{PexExecutionMode.ZIPAPP.value}'` as well.
        """
    )


class PexIncludeRequirementsField(BoolField):
    alias = "include_requirements"
    default = True
    help = help_text(
        """
        Whether to include the third party requirements the binary depends on in the
        packaged PEX file.
        """
    )


class PexIncludeSourcesField(BoolField):
    alias = "include_sources"
    default = True
    help = help_text(
        """
        Whether to include your first party sources the binary uses in the packaged PEX file.
        """
    )


class PexIncludeToolsField(BoolField):
    alias = "include_tools"
    default = False
    help = help_text(
        """
        Whether to include Pex tools in the PEX bootstrap code.

        With tools included, the generated PEX file can be executed with `PEX_TOOLS=1 <pex file> --help`
        to gain access to all the available tools.
        """
    )


class PexVenvSitePackagesCopies(BoolField):
    alias = "venv_site_packages_copies"
    default = False
    help = help_text(
        """
        If execution_mode is venv, populate the venv site packages using hard links or copies of resolved PEX dependencies instead of symlinks.

        This can be used to work around problems with tools or libraries that are confused by symlinked source files.
        """
    )


class PexVenvHermeticScripts(BoolField):
    alias = "venv_hermetic_scripts"
    default = True
    help = help_text(
        """
        If execution_mode is "venv", emit a hermetic venv `pex` script and hermetic console scripts.

        The venv `pex` script and the venv console scripts are constructed to be hermetic by
        default; Python is executed with `-sE` to restrict the `sys.path` to the PEX venv contents
        only. Setting this field to `False` elides the Python `-sE` restrictions and can be used to
        interoperate with frameworks that use `PYTHONPATH` manipulation to run code.
        """
    )


_PEX_BINARY_COMMON_FIELDS = (
    EnvironmentField,
    InterpreterConstraintsField,
    PythonResolveField,
    PexBinaryDependenciesField,
    PexPlatformsField,
    PexCompletePlatformsField,
    PexResolveLocalPlatformsField,
    PexInheritPathField,
    PexStripEnvField,
    PexIgnoreErrorsField,
    PexShBootField,
    PexShebangField,
    PexEmitWarningsField,
    PexLayoutField,
    PexExecutionModeField,
    PexIncludeRequirementsField,
    PexIncludeSourcesField,
    PexIncludeToolsField,
    PexVenvSitePackagesCopies,
    PexVenvHermeticScripts,
    RestartableField,
)


class PexBinary(Target):
    alias = "pex_binary"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        *_PEX_BINARY_COMMON_FIELDS,
        PexEntryPointField,
        PexScriptField,
        PexExecutableField,
        PexArgsField,
        PexEnvField,
        OutputPathField,
    )
    help = help_text(
        f"""
        A Python target that can be converted into an executable PEX file.

        PEX files are self-contained executable files that contain a complete Python environment
        capable of running the target. For more information, see {doc_url('pex')}.
        """
    )

    def validate(self) -> None:
        got_entry_point = self[PexEntryPointField].value is not None
        got_script = self[PexScriptField].value is not None
        got_executable = self[PexExecutableField].value is not None

        if (got_entry_point + got_script + got_executable) > 1:
            raise InvalidTargetException(
                softwrap(
                    f"""
                    The `{self.alias}` target {self.address} cannot set more than one of the
                    `{self[PexEntryPointField].alias}`, `{self[PexScriptField].alias}`, and
                    `{self[PexExecutableField].alias}` fields at the same time.
                    To fix, please remove all but one.
                    """
                )
            )


class PexEntryPointsField(StringSequenceField, AsyncFieldMixin):
    alias = "entry_points"
    default = None
    help = help_text(
        """
        The entry points for each binary, i.e. what gets run when when executing `./my_app.pex.`

        Use a file name, relative to the BUILD file, like `app.py`. You can also set the
        function to run, like `app.py:func`. Pants will convert these file names into well-formed
        entry points, like `app.py:func` into `path.to.app:func.`

        If you want the entry point to be for a third-party dependency or to use a console
        script, use the `pex_binary` target directly.
        """
    )


class PexBinariesOverrideField(OverridesField):
    help = help_text(
        f"""
        Override the field values for generated `{PexBinary.alias}` targets.

        Expects a dictionary mapping values from the `entry_points` field to a dictionary for
        their overrides. You may either use a single string or a tuple of strings to override
        multiple targets.

        For example:

            overrides={{
              "foo.py": {{"execution_mode": "venv"]}},
              "bar.py:main": {{"restartable": True]}},
              ("foo.py", "bar.py:main"): {{"tags": ["legacy"]}},
            }}

        Every key is validated to belong to this target's `entry_points` field.

        If you'd like to override a field's value for every `{PexBinary.alias}` target
        generated by this target, change the field directly on this target rather than using the
        `overrides` field.

        You can specify the same `entry_point` in multiple keys, so long as you don't override the
        same field more than one time for the `entry_point`.
        """
    )


class PexBinariesGeneratorTarget(TargetGenerator):
    alias = "pex_binaries"
    help = help_text(
        """
        Generate a `pex_binary` target for each entry_point in the `entry_points` field.

        This is solely meant to reduce duplication when you have multiple scripts in the same
        directory; it's valid to use a distinct `pex_binary` target for each script/binary
        instead.

        This target generator does not work well to generate `pex_binary` targets where the entry
        point is for a third-party dependency. Dependency inference will not work for those, so
        you will have to set lots of custom metadata for each binary; prefer an explicit
        `pex_binary` target in that case. This target generator works best when the entry point
        is a first-party file, like `app.py` or `app.py:main`.
        """
    )
    generated_target_cls = PexBinary
    core_fields = (
        *COMMON_TARGET_FIELDS,
        PexEntryPointsField,
        PexBinariesOverrideField,
    )
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = _PEX_BINARY_COMMON_FIELDS


class PexBinaryDefaults(Subsystem):
    options_scope = "pex-binary-defaults"
    help = "Default settings for creating PEX executables."

    emit_warnings = BoolOption(
        default=True,
        help=softwrap(
            """
            Whether built PEX binaries should emit PEX warnings at runtime by default.

            Can be overridden by specifying the `emit_warnings` parameter of individual
            `pex_binary` targets
            """
        ),
        advanced=True,
    )
    resolve_local_platforms = BoolOption(
        default=False,
        help=softwrap(
            f"""
            For each of the `{PexPlatformsField.alias}` specified for a `{PexBinary.alias}`
            target, attempt to find a local interpreter that matches.

            If a matching interpreter is found, use the interpreter to resolve distributions and
            build any that are only available in source distribution form. If no matching interpreter
            is found (or if this option is `False`), resolve for the platform by accepting
            only pre-built binary distributions (wheels).
            """
        ),
        advanced=True,
    )


# -----------------------------------------------------------------------------------------------
# `python_test` and `python_tests` targets
# -----------------------------------------------------------------------------------------------


class PythonTestSourceField(PythonSourceField):
    expected_file_extensions = (".py", "")  # Note that this does not include `.pyi`.

    def validate_resolved_files(self, files: Sequence[str]) -> None:
        super().validate_resolved_files(files)
        file = files[0]
        file_name = os.path.basename(file)
        if file_name == "conftest.py":
            raise InvalidFieldException(
                softwrap(
                    f"""
                    The {repr(self.alias)} field in target {self.address} should not be set to the
                    file 'conftest.py', but was set to {repr(self.value)}.

                    Instead, use a `python_source` target or the target generator `python_test_utils`.
                    You can run `{bin_name()} tailor` after removing this target ({self.address}) to
                    autogenerate a `python_test_utils` target.
                    """
                )
            )


class PythonTestsDependenciesField(PythonDependenciesField):
    supports_transitive_excludes = True


# TODO This field class should extend from a core `TestTimeoutField` once the deprecated options in `pytest` get removed.
class PythonTestsTimeoutField(IntField):
    alias = "timeout"
    help = help_text(
        """
        A timeout (in seconds) used by each test file belonging to this target.

        If unset, will default to `[test].timeout_default`; if that option is also unset,
        then the test will never time out. Will never exceed `[test].timeout_maximum`. Only
        applies if the option `--test-timeouts` is set to true (the default).
        """
    )
    valid_numbers = ValidNumbers.positive_only

    def calculate_from_global_options(self, test: TestSubsystem, pytest: PyTest) -> Optional[int]:
        """Determine the timeout (in seconds) after resolving conflicting global options in the
        `pytest` and `test` scopes.

        This function is deprecated and should be replaced by the similarly named one in
        `TestTimeoutField` once the deprecated options in the `pytest` scope are removed.
        """

        enabled = test.options.timeouts
        timeout_default = test.options.timeout_default
        timeout_maximum = test.options.timeout_maximum

        if not enabled:
            return None
        if self.value is None:
            if timeout_default is None:
                return None
            result = cast(int, timeout_default)
        else:
            result = self.value
        if timeout_maximum is not None:
            return min(result, cast(int, timeout_maximum))
        return result


class PythonTestsExtraEnvVarsField(TestExtraEnvVarsField):
    pass


class PythonTestsXdistConcurrencyField(IntField):
    alias = "xdist_concurrency"
    help = help_text(
        """
        Maximum number of CPUs to allocate to run each test file belonging to this target.

        Tests are spread across multiple CPUs using `pytest-xdist`
        (https://pytest-xdist.readthedocs.io/en/latest/index.html).
        Use of `pytest-xdist` must be enabled using the `[pytest].xdist_enabled` option for
        this field to have an effect.

        If `pytest-xdist` is enabled and this field is unset, Pants will attempt to derive
        the concurrency for test sources by counting the number of tests in each file.

        Set this field to `0` to explicitly disable use of `pytest-xdist` for a target.
        """
    )


class PythonTestsBatchCompatibilityTagField(TestsBatchCompatibilityTagField):
    help = help_text(TestsBatchCompatibilityTagField.format_help("python_test", "pytest"))


class SkipPythonTestsField(BoolField):
    alias = "skip_tests"
    default = False
    help = "If true, don't run this target's tests."


_PYTHON_TEST_MOVED_FIELDS = (
    PythonTestsDependenciesField,
    PythonResolveField,
    PythonRunGoalUseSandboxField,
    PythonTestsTimeoutField,
    PythonTestsXdistConcurrencyField,
    PythonTestsBatchCompatibilityTagField,
    RuntimePackageDependenciesField,
    PythonTestsExtraEnvVarsField,
    InterpreterConstraintsField,
    SkipPythonTestsField,
    EnvironmentField,
)


class PythonTestTarget(Target):
    alias = "python_test"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        *_PYTHON_TEST_MOVED_FIELDS,
        PythonTestsDependenciesField,
        PythonTestSourceField,
    )
    help = help_text(
        f"""
        A single Python test file, written in either Pytest style or unittest style.

        All test util code, including `conftest.py`, should go into a dedicated `python_source`
        target and then be included in the `dependencies` field. (You can use the
        `python_test_utils` target to generate these `python_source` targets.)

        See {doc_url('python-test-goal')}
        """
    )


class PythonTestsGeneratingSourcesField(PythonGeneratingSourcesBase):
    expected_file_extensions = (".py", "")  # Note that this does not include `.pyi`.
    default = ("test_*.py", "*_test.py", "tests.py")
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['test_*.py', '*_test.py', 'tests.py']`"
    )

    def validate_resolved_files(self, files: Sequence[str]) -> None:
        super().validate_resolved_files(files)
        # We don't technically need to error for `conftest.py` here because `PythonTestSourceField`
        # already validates this, but we get a better error message this way so that users don't
        # have to reason about generated targets.
        conftest_files = [fp for fp in files if os.path.basename(fp) == "conftest.py"]
        if conftest_files:
            raise InvalidFieldException(
                softwrap(
                    f"""
                    The {repr(self.alias)} field in target {self.address} should not include the
                    file 'conftest.py', but included these: {conftest_files}.

                    Instead, use a `python_source` target or the target generator `python_test_utils`.
                    You can run `{bin_name()} tailor` after removing the files from the
                    {repr(self.alias)} field of this target ({self.address}) to autogenerate a
                    `python_test_utils` target.
                    """
                )
            )


class PythonTestsOverrideField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        PythonTestTarget.alias,
        """
        overrides={
            "foo_test.py": {"timeout": 120},
            "bar_test.py": {"timeout": 200},
            ("foo_test.py", "bar_test.py"): {"tags": ["slow_tests"]},
        }
        """,
    )


class PythonTestsGeneratorTarget(TargetFilesGenerator):
    alias = "python_tests"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        PythonTestsGeneratingSourcesField,
        PythonTestsOverrideField,
    )
    generated_target_cls = PythonTestTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = _PYTHON_TEST_MOVED_FIELDS
    settings_request_cls = PythonFilesGeneratorSettingsRequest
    help = "Generate a `python_test` target for each file in the `sources` field."


# -----------------------------------------------------------------------------------------------
# `python_source`, `python_sources`, and `python_test_utils` targets
# -----------------------------------------------------------------------------------------------


class PythonSourceTarget(Target):
    alias = "python_source"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        InterpreterConstraintsField,
        PythonDependenciesField,
        PythonResolveField,
        PythonRunGoalUseSandboxField,
        PythonSourceField,
        RestartableField,
    )
    help = "A single Python source file."


class PythonSourcesOverridesField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        PythonSourceTarget.alias,
        """
        overrides={
            "foo.py": {"skip_pylint": True]},
            "bar.py": {"skip_flake8": True]},
            ("foo.py", "bar.py"): {"tags": ["linter_disabled"]},
        }"
        """,
    )


class PythonTestUtilsGeneratingSourcesField(PythonGeneratingSourcesBase):
    default = ("conftest.py", "test_*.pyi", "*_test.pyi", "tests.pyi")
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['conftest.py', 'test_*.pyi', '*_test.pyi', 'tests.pyi']`"
    )


class PythonSourcesGeneratingSourcesField(PythonGeneratingSourcesBase):
    default = (
        ("*.py", "*.pyi")
        + tuple(f"!{pat}" for pat in PythonTestsGeneratingSourcesField.default)
        + tuple(f"!{pat}" for pat in PythonTestUtilsGeneratingSourcesField.default)
    )
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['example.py', 'new_*.py', '!old_ignore.py']`"
    )


class PythonTestUtilsGeneratorTarget(TargetFilesGenerator):
    alias = "python_test_utils"
    # Keep in sync with `PythonSourcesGeneratorTarget`, outside of the `sources` field.
    core_fields = (
        *COMMON_TARGET_FIELDS,
        PythonTestUtilsGeneratingSourcesField,
        PythonSourcesOverridesField,
    )
    generated_target_cls = PythonSourceTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (
        PythonResolveField,
        PythonRunGoalUseSandboxField,
        PythonDependenciesField,
        InterpreterConstraintsField,
    )
    settings_request_cls = PythonFilesGeneratorSettingsRequest
    help = help_text(
        """
        Generate a `python_source` target for each file in the `sources` field.

        This target generator is intended for test utility files like `conftest.py` or
        `my_test_utils.py`. Technically, it generates `python_source` targets in the exact same
        way as the `python_sources` target generator does, only that the `sources` field has a
        different default. So it is valid to use `python_sources` instead. However, this target
        can be helpful to better model your code by keeping separate test support files vs.
        production files.
        """
    )


class PythonSourcesGeneratorTarget(TargetFilesGenerator):
    alias = "python_sources"
    # Keep in sync with `PythonTestUtilsGeneratorTarget`, outside of the `sources` field.
    core_fields = (
        *COMMON_TARGET_FIELDS,
        PythonSourcesGeneratingSourcesField,
        PythonSourcesOverridesField,
    )
    generated_target_cls = PythonSourceTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (
        PythonResolveField,
        PythonRunGoalUseSandboxField,
        PythonDependenciesField,
        InterpreterConstraintsField,
        RestartableField,
    )
    settings_request_cls = PythonFilesGeneratorSettingsRequest
    help = help_text(
        """
        Generate a `python_source` target for each file in the `sources` field.

        You can either use this target generator or `python_test_utils` for test utility files
        like `conftest.py`. They behave identically, but can help to better model and keep
        separate test support files vs. production files.
        """
    )


# -----------------------------------------------------------------------------------------------
# `python_requirement` target
# -----------------------------------------------------------------------------------------------


class _PipRequirementSequenceField(Field):
    value: tuple[PipRequirement, ...]

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Iterable[str]], address: Address
    ) -> Tuple[PipRequirement, ...]:
        value = super().compute_value(raw_value, address)
        if value is None:
            return ()
        invalid_type_error = InvalidFieldTypeException(
            address,
            cls.alias,
            value,
            expected_type="an iterable of pip-style requirement strings (e.g. a list)",
        )
        if isinstance(value, str) or not isinstance(value, collections.abc.Iterable):
            raise invalid_type_error
        result = []
        for v in value:
            # We allow passing a pre-parsed `PipRequirement`. This is intended for macros which
            # might have already parsed so that we can avoid parsing multiple times.
            if isinstance(v, PipRequirement):
                result.append(v)
            elif isinstance(v, str):
                try:
                    parsed = PipRequirement.parse(
                        v, description_of_origin=f"the '{cls.alias}' field for the target {address}"
                    )
                except ValueError as e:
                    raise InvalidFieldException(e)
                result.append(parsed)
            else:
                raise invalid_type_error
        return tuple(result)


class PythonRequirementDependenciesField(Dependencies):
    pass


class PythonRequirementsField(_PipRequirementSequenceField):
    alias = "requirements"
    required = True
    help = help_text(
        """
        A pip-style requirement string, e.g. `["Django==3.2.8"]`.

        You can specify multiple requirements for the same project in order to use environment
        markers, such as `["foo>=1.2,<1.3 ; python_version>\'3.6\'", "foo==0.9 ;
        python_version<'3'\"]`.

        If the requirement depends on some other requirement to work, such as needing
        `setuptools` to be built, use the `dependencies` field instead.
        """
    )


_default_module_mapping_url = git_url(
    "src/python/pants/backend/python/dependency_inference/default_module_mapping.py"
)


class PythonRequirementModulesField(StringSequenceField):
    alias = "modules"
    help = help_text(
        f"""
        The modules this requirement provides (used for dependency inference).

        For example, the requirement `setuptools` provides `["setuptools", "pkg_resources",
        "easy_install"]`.

        Usually you can leave this field off. If unspecified, Pants will first look at the
        default module mapping ({_default_module_mapping_url}), and then will default to
        the normalized project name. For example, the requirement `Django` would default to
        the module `django`.

        Mutually exclusive with the `type_stub_modules` field.
        """
    )


class PythonRequirementTypeStubModulesField(StringSequenceField):
    alias = "type_stub_modules"
    help = help_text(
        f"""
        The modules this requirement provides if the requirement is a type stub (used for
        dependency inference).

        For example, the requirement `types-requests` provides `["requests"]`.

        Usually you can leave this field off. If unspecified, Pants will first look at the
        default module mapping ({_default_module_mapping_url}). If not found _and_ the
        requirement name starts with `types-` or `stubs-`, or ends with `-types` or `-stubs`,
        will default to that requirement name without the prefix/suffix. For example,
        `types-requests` would default to `requests`. Otherwise, will be treated like a normal
        requirement (see the `modules` field).

        Mutually exclusive with the `modules` field.
        """
    )


def normalize_module_mapping(
    mapping: Mapping[str, Iterable[str]] | None
) -> FrozenDict[str, tuple[str, ...]]:
    return FrozenDict({canonicalize_project_name(k): tuple(v) for k, v in (mapping or {}).items()})


class PythonRequirementResolveField(PythonResolveField):
    alias = "resolve"
    required = False
    help = help_text(
        """
        The resolve from `[python].resolves` that this requirement is included in.

        If not defined, will default to `[python].default_resolve`.

        When generating a lockfile for a particular resolve via the `generate-lockfiles` goal,
        it will include all requirements that are declared with that resolve.
        First-party targets like `python_source` and `pex_binary` then declare which resolve
        they use via their `resolve` field; so, for your first-party code to use a
        particular `python_requirement` target, that requirement must be included in the resolve
        used by that code.
        """
    )


class PythonRequirementFindLinksField(StringSequenceField):
    # NB: This is solely used for `pants_requirements` target generation
    alias = "_find_links"
    required = False
    default = ()
    help = "<Internal>"


class PythonRequirementEntryPointField(EntryPointField):
    # Specialist subclass for matching `PythonRequirementTarget` when running.
    pass


class PythonRequirementTarget(Target):
    alias = "python_requirement"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        PythonRequirementsField,
        PythonRequirementDependenciesField,
        PythonRequirementModulesField,
        PythonRequirementTypeStubModulesField,
        PythonRequirementResolveField,
        PythonRequirementEntryPointField,
        PythonRequirementFindLinksField,
    )
    help = help_text(
        f"""
        A Python requirement installable by pip.

        This target is useful when you want to declare Python requirements inline in a
        BUILD file. If you have a `requirements.txt` file already, you can instead use
        the target generator `python_requirements` to convert each
        requirement into a `python_requirement` target automatically. For Poetry, use
        `poetry_requirements`.

        See {doc_url('python-third-party-dependencies')}.
        """
    )

    def validate(self) -> None:
        if (
            self[PythonRequirementModulesField].value
            and self[PythonRequirementTypeStubModulesField].value
        ):
            raise InvalidTargetException(
                softwrap(
                    f"""
                    The `{self.alias}` target {self.address} cannot set both the
                    `{self[PythonRequirementModulesField].alias}` and
                    `{self[PythonRequirementTypeStubModulesField].alias}` fields at the same time.
                    To fix, please remove one.
                    """
                )
            )


# -----------------------------------------------------------------------------------------------
# `python_distribution` target
# -----------------------------------------------------------------------------------------------


# See `target_types_rules.py` for a dependency injection rule.
class PythonDistributionDependenciesField(Dependencies):
    supports_transitive_excludes = True


class PythonProvidesField(ScalarField, AsyncFieldMixin):
    alias = "provides"
    expected_type = PythonArtifact
    expected_type_help = "python_artifact(name='my-dist', **kwargs)"
    value: PythonArtifact
    required = True
    help = help_text(
        f"""
        The setup.py kwargs for the external artifact built from this target.

        You must define `name`. You can also set almost any keyword argument accepted by setup.py
        in the `setup()` function:
        (https://packaging.python.org/guides/distributing-packages-using-setuptools/#setup-args).

        See {doc_url('plugins-setup-py')} for how to write a plugin to dynamically generate kwargs.
        """
    )

    @classmethod
    def compute_value(cls, raw_value: Optional[PythonArtifact], address: Address) -> PythonArtifact:
        return cast(PythonArtifact, super().compute_value(raw_value, address))


class PythonDistributionEntryPointsField(NestedDictStringToStringField, AsyncFieldMixin):
    alias = "entry_points"
    required = False
    help = help_text(
        f"""
        Any entry points, such as `console_scripts` and `gui_scripts`.

        Specify as a nested dictionary, with a dictionary for each type of entry point,
        e.g. `console_scripts` vs. `gui_scripts`. Each dictionary maps the entry point name to
        either a setuptools entry point (`"path.to.module:func"`) or a Pants target address to a
        `pex_binary` target.

        Example:

            entry_points={{
              "console_scripts": {{
                "my-script": "project.app:main",
                "another-script": "project/subdir:pex_binary_tgt"
              }}
            }}

        Note that Pants will assume that any value that either starts with `:` or has `/` in it,
        is a target address to a `pex_binary` target. Otherwise, it will assume it's a setuptools
        entry point as defined by
        https://packaging.python.org/specifications/entry-points/#entry-points-specification. Use
        `//` as a prefix for target addresses if you need to disambiguate.

        Pants will attempt to infer dependencies, which you can confirm by running:

            {bin_name()} dependencies <python_distribution target address>
        """
    )


class PythonDistributionOutputPathField(StringField, AsyncFieldMixin):
    help = help_text(
        """
        The path to the directory to write the distribution file to, relative the dist directory.

        If undefined, this defaults to the empty path, i.e. the output goes at the top
        level of the dist dir.
        """
    )
    alias = "output_path"
    default = ""


@dataclass(frozen=True)
class PythonDistributionEntryPoint:
    """Note that this stores if the entry point comes from an address to a `pex_binary` target."""

    entry_point: EntryPoint
    pex_binary_address: Optional[Address]


# See `target_type_rules.py` for the `Resolve..Request -> Resolved..` rule
@dataclass(frozen=True)
class ResolvedPythonDistributionEntryPoints:
    # E.g. {"console_scripts": {"ep": PythonDistributionEntryPoint(...)}}.
    val: FrozenDict[str, FrozenDict[str, PythonDistributionEntryPoint]] = FrozenDict()

    @property
    def explicit_modules(self) -> FrozenDict[str, FrozenDict[str, EntryPoint]]:
        """Filters out all entry points from pex binary targets."""
        return FrozenDict(
            {
                category: FrozenDict(
                    {
                        ep_name: ep_val.entry_point
                        for ep_name, ep_val in entry_points.items()
                        if not ep_val.pex_binary_address
                    }
                )
                for category, entry_points in self.val.items()
            }
        )

    @property
    def pex_binary_addresses(self) -> Addresses:
        """Returns the addresses to all pex binary targets owning entry points used."""
        return Addresses(
            ep_val.pex_binary_address
            for category, entry_points in self.val.items()
            for ep_val in entry_points.values()
            if ep_val.pex_binary_address
        )


@dataclass(frozen=True)
class ResolvePythonDistributionEntryPointsRequest:
    """Looks at the entry points to see if it is a setuptools entry point, or a BUILD target address
    that should be resolved into a setuptools entry point.

    If the `entry_points_field` is present, inspect the specified entry points.
    If the `provides_field` is present, inspect the `provides_field.kwargs["entry_points"]`.

    This is to support inspecting one or the other depending on use case, using the same
    logic for resolving pex_binary addresses etc.
    """

    entry_points_field: Optional[PythonDistributionEntryPointsField] = None
    provides_field: Optional[PythonProvidesField] = None

    def __post_init__(self):
        # Must provide at least one of these fields.
        assert self.entry_points_field or self.provides_field


class WheelField(BoolField):
    alias = "wheel"
    default = True
    help = "Whether to build a wheel for the distribution."


class SDistField(BoolField):
    alias = "sdist"
    default = True
    help = "Whether to build an sdist for the distribution."


class ConfigSettingsField(DictStringToStringSequenceField):
    """Values for config_settings (see https://www.python.org/dev/peps/pep-0517/#config-settings).

    NOTE: PEP-517 appears to be ill-defined wrt value types in config_settings. It mentions that:

    - Build backends may assign any semantics they like to this dictionary, i.e., the backend
      decides what the value types it accepts are.

    - Build frontends should support string values, and may also support other mechanisms
      (apparently meaning other types).

    Presumably, a well-behaved frontend is supposed to work with any backend, but it cannot
    do so without knowledge of what types each backend expects in the config_settings values,
    as it has to set those values.

    See a similar discussion in the context of Pip: https://github.com/pypa/pip/issues/5771 .

    In practice, the backend we currently care about, setuptools.build_meta, expects a
    dict with one key, --global-option, whose value is a sequence of cmd-line setup options.
    It ignores all other keys.  So, to accommodate setuptools, the type of this field is
    DictStringToStringSequenceField, and hopefully other backends we may encounter in the future
    can work with this too.  If we need to handle values that can be strings or string sequences,
    as demonstrated in the example in PEP-517, then we will need to change this field's type
    to an as-yet-nonexistent "DictStringToStringOrStringSequenceField".
    """


class WheelConfigSettingsField(ConfigSettingsField):
    alias = "wheel_config_settings"
    help = "PEP-517 config settings to pass to the build backend when building a wheel."


class SDistConfigSettingsField(ConfigSettingsField):
    alias = "sdist_config_settings"
    help = "PEP-517 config settings to pass to the build backend when building an sdist."


class BuildBackendEnvVarsField(StringSequenceField):
    alias = "env_vars"
    required = False
    help = help_text(
        """
        Environment variables to set when running the PEP-517 build backend.

        Entries are either strings in the form `ENV_VAR=value` to set an explicit value;
        or just `ENV_VAR` to copy the value from Pants's own environment.
        """
    )


class GenerateSetupField(TriBoolField):
    alias = "generate_setup"
    required = False
    # The default behavior if this field is unspecified is controlled by the
    # --generate-setup-default option in the setup-py-generation scope.
    default = None

    help = help_text(
        """
        Whether to generate setup information for this distribution, based on analyzing
        sources and dependencies. Set to False to use existing setup information, such as
        existing `setup.py`, `setup.cfg`, `pyproject.toml` files or similar.
        """
    )


class LongDescriptionPathField(StringField):
    alias = "long_description_path"
    required = False

    help = help_text(
        """
        Path to a file that will be used to fill the `long_description` field in `setup.py`.

        Path is relative to the build root.

        Alternatively, you can set the `long_description` in the `provides` field, but not both.

        This field won't automatically set `long_description_content_type` field for you.
        You have to specify this field yourself in the `provides` field.
        """
    )


class PythonDistribution(Target):
    alias = "python_distribution"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        InterpreterConstraintsField,
        PythonDistributionDependenciesField,
        PythonDistributionEntryPointsField,
        PythonProvidesField,
        GenerateSetupField,
        WheelField,
        SDistField,
        WheelConfigSettingsField,
        SDistConfigSettingsField,
        BuildBackendEnvVarsField,
        LongDescriptionPathField,
        PythonDistributionOutputPathField,
    )
    help = help_text(
        f"""
        A publishable Python setuptools distribution (e.g. an sdist or wheel).

        See {doc_url('python-distributions')}.
        """
    )


# -----------------------------------------------------------------------------------------------
# `vcs_version` target
# -----------------------------------------------------------------------------------------------

# The vcs_version target is defined and registered here in the python backend because the VCS
# version functionality uses a lot of python machinery in its implementation, and because it is
# (at least at the time of writing) highly unlikely to be used outside a python context in practice.
# However, hypothetically, the source file generated by a vcs_version target can be in any language.
# Therefore any language-specific fields (such as python_resolve) are registered as plugin fields
# instead of provided directly here, even though the only language in question is python.


class VCSVersionDummySourceField(OptionalSingleSourceField):
    """A dummy SourceField for participation in the codegen machinery."""

    alias = "_dummy_source"  # Leading underscore omits the field from help.
    help = "A version string generated from VCS information"


class VersionTagRegexField(StringField):
    default = r"^(?:[\w-]+-)?(?P<version>[vV]?\d+(?:\.\d+){0,2}[^\+]*)(?:\+.*)?$"
    alias = "tag_regex"
    help = help_text(
        """
        A Python regex string to extract the version string from a VCS tag.

        The regex needs to contain either a single match group, or a group named version,
        that captures the actual version information.

        Note that this is unrelated to the tags field and Pants's own tags concept.

        See https://github.com/pypa/setuptools_scm for implementation details.
        """
    )


class VersionGenerateToField(StringField):
    required = True
    alias = "generate_to"
    help = help_text(
        """
        Generate the version data to this relative path, using the template field.

        Note that the generated output will not be written to disk in the source tree, but
        will be available as a generated dependency to code that depends on this target.
        """
    )


class VersionTemplateField(StringField):
    required = True
    alias = "template"
    help = help_text(
        """
        Generate the version data using this format string, which takes a version format kwarg.

        E.g., `'version = "{version}"'`
        """
    )


class VersionVersionSchemeField(StringField):
    alias = "version_scheme"
    help = help_text(
        """
        The version scheme to configure `setuptools_scm` to use.
        See https://setuptools-scm.readthedocs.io/en/latest/extending/#available-implementations
        """
    )


class VersionLocalSchemeField(StringField):
    alias = "local_scheme"
    help = help_text(
        """
        The local scheme to configure `setuptools_scm` to use.
        See https://setuptools-scm.readthedocs.io/en/latest/extending/#available-implementations_1
        """
    )


class VCSVersion(Target):
    alias = "vcs_version"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        VersionTagRegexField,
        VersionVersionSchemeField,
        VersionLocalSchemeField,
        VCSVersionDummySourceField,
        VersionGenerateToField,
        VersionTemplateField,
    )
    help = help_text(
        f"""
        Generates a version string from VCS state.

        Uses a constrained but useful subset of the full functionality of setuptools_scm
        (https://github.com/pypa/setuptools_scm). These constraints avoid pitfalls in the
        interaction of setuptools_scm with Pants's hermetic environments.

        In particular, we ignore any existing setuptools_scm config. Instead you must provide
        a subset of that config in this target's fields.

        If you need functionality that is not currently exposed here, please reach out to us at
        {doc_url("getting-help")}.
        """
    )
