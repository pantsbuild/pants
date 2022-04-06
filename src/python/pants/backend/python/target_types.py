# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import collections.abc
import logging
import os.path
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from textwrap import dedent
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
from pants.backend.python.pip_requirement import PipRequirement
from pants.backend.python.subsystems.setup import PythonSetup
from pants.core.goals.generate_lockfiles import UnrecognizedResolveNamesError
from pants.core.goals.package import OutputPathField
from pants.core.goals.run import RestartableField
from pants.core.goals.test import RuntimePackageDependenciesField
from pants.engine.addresses import Address, Addresses
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AsyncFieldMixin,
    BoolField,
    Dependencies,
    DictStringToStringSequenceField,
    Field,
    IntField,
    InvalidFieldException,
    InvalidFieldTypeException,
    InvalidTargetException,
    MultipleSourcesField,
    NestedDictStringToStringField,
    OverridesField,
    ScalarField,
    SecondaryOwnerMixin,
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
)
from pants.option.option_types import BoolOption
from pants.option.subsystem import Subsystem
from pants.source.filespec import Filespec
from pants.util.docutil import bin_name, doc_url, git_url
from pants.util.frozendict import FrozenDict

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pants.backend.python.subsystems.pytest import PyTest


# -----------------------------------------------------------------------------------------------
# Common fields
# -----------------------------------------------------------------------------------------------


class PythonSourceField(SingleSourceField):
    # Note that Python scripts often have no file ending.
    expected_file_extensions: ClassVar[tuple[str, ...]] = ("", ".py", ".pyi")


class PythonGeneratingSourcesBase(MultipleSourcesField):
    expected_file_extensions: ClassVar[tuple[str, ...]] = ("", ".py", ".pyi")


class InterpreterConstraintsField(StringSequenceField):
    alias = "interpreter_constraints"
    help = (
        "The Python interpreters this code is compatible with.\n\nEach element should be written "
        "in pip-style format, e.g. `CPython==2.7.*` or `CPython>=3.6,<4`. You can leave off "
        "`CPython` as a shorthand, e.g. `>=2.7` will be expanded to `CPython>=2.7`.\n\nSpecify "
        "more than one element to OR the constraints, e.g. `['PyPy==3.7.*', 'CPython==3.7.*']` "
        "means either PyPy 3.7 _or_ CPython 3.7.\n\nIf the field is not set, it will default to "
        "the option `[python].interpreter_constraints`.\n\n"
        f"See {doc_url('python-interpreter-compatibility')} for how these interpreter "
        "constraints are merged with the constraints of dependencies."
    )

    def value_or_global_default(self, python_setup: PythonSetup) -> Tuple[str, ...]:
        """Return either the given `compatibility` field or the global interpreter constraints.

        If interpreter constraints are supplied by the CLI flag, return those only.
        """
        return python_setup.compatibility_or_constraints(self.value)


class PythonResolveField(StringField, AsyncFieldMixin):
    alias = "resolve"
    required = False
    help = (
        "The resolve from `[python].resolves` to use.\n\n"
        "If not defined, will default to `[python].default_resolve`.\n\n"
        "All dependencies must share the same value for their `resolve` field."
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
                f"The {given} cannot be blank. It must indicate a Python module by name or path "
                f"and an optional nullary function in that module separated by a colon, i.e.: "
                f"module_name_or_path(':'function_name)?"
            )
        module_or_path, sep, func = entry_point.partition(":")
        if not module_or_path:
            raise ValueError(f"The {given} must specify a module; given: {value!r}")
        if ":" in func:
            raise ValueError(
                f"The {given} can only contain one colon separating the entry point's module from "
                f"the entry point function in that module; given: {value!r}"
            )
        if sep and not func:
            logger.warning(
                f"Assuming no entry point function and stripping trailing ':' from the {given}: "
                f"{value!r}. Consider deleting it to make it clear no entry point function is "
                f"intended."
            )
        return cls(module=module_or_path, function=func if func else None)

    def __post_init__(self):
        if ":" in self.module:
            raise ValueError(
                "The `:` character is not valid in a module name. Given an entry point module of "
                f"{self.module}. Did you mean to use EntryPoint.parse?"
            )
        if self.function and ":" in self.function:
            raise ValueError(
                "The `:` character is not valid in a function name. Given an entry point function"
                f" of {self.function}."
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


class PexEntryPointField(AsyncFieldMixin, SecondaryOwnerMixin, Field):
    alias = "entry_point"
    default = None
    help = (
        "Set the entry point, i.e. what gets run when executing `./my_app.pex`, to a module.\n\n"
        "You can specify a full module like 'path.to.module' and 'path.to.module:func', or use a "
        "shorthand to specify a file name, using the same syntax as the `sources` field:\n\n"
        "  1) 'app.py', Pants will convert into the module `path.to.app`;\n"
        "  2) 'app.py:func', Pants will convert into `path.to.app:func`.\n\n"
        "You must use the file name shorthand for file arguments to work with this target.\n\n"
        "You may either set this field or the `script` field, but not both. Leave off both fields "
        "to have no entry point."
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

    @property
    def filespec(self) -> Filespec:
        if self.value is None or not self.value.module.endswith(".py"):
            return {"includes": []}
        full_glob = os.path.join(self.address.spec_path, self.value.module)
        return {"includes": [full_glob]}


# See `target_types_rules.py` for the `ResolvePexEntryPointRequest -> ResolvedPexEntryPoint` rule.
@dataclass(frozen=True)
class ResolvedPexEntryPoint:
    val: EntryPoint | None
    file_name_used: bool


@dataclass(frozen=True)
class ResolvePexEntryPointRequest:
    """Determine the `entry_point` for a `pex_binary` after applying all syntactic sugar."""

    entry_point_field: PexEntryPointField


class PexScriptField(Field):
    alias = "script"
    default = None
    help = (
        "Set the entry point, i.e. what gets run when executing `./my_app.pex`, to a script or "
        "console_script as defined by any of the distributions in the PEX.\n\n"
        "You may either set this field or the `entry_point` field, but not both. Leave off both "
        "fields to have no entry point."
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


class PexPlatformsField(StringSequenceField):
    alias = "platforms"
    help = (
        "The abbreviated platforms the built PEX should be compatible with.\n\nThere must be built "
        "wheels available for all of the foreign platforms, rather than sdists.\n\n"
        "You can give a list of multiple platforms to create a multiplatform PEX, "
        "meaning that the PEX will be executable in all of the supported environments.\n\n"
        "Platforms should be in the format defined by Pex "
        "(https://pex.readthedocs.io/en/latest/buildingpex.html#platform), i.e. "
        'PLATFORM-IMPL-PYVER-ABI (e.g. "linux_x86_64-cp-37-cp37m", '
        '"macosx_10.12_x86_64-cp-310-cp310"):\n\n'
        "  - PLATFORM: the host platform, e.g. "
        '"linux-x86_64", "macosx-10.12-x86_64".\n  - IMPL: the Python implementation abbreviation, '
        'e.g. "cp" or "pp".\n  - PYVER: a two or more digit string representing the python '
        'major/minor version (e.g., "37" or "310") or else a component dotted version string (e.g.,'
        '"3.7" or "3.10.1").\n  - ABI: the ABI tag, e.g. "cp37m", "cp310", "abi3", "none".\n\nNote '
        "that using an abbreviated platform means that certain resolves will fail when they "
        "encounter environment markers that cannot be deduced from the abbreviated platform "
        "string. A common example of this is 'python_full_version' which requires knowing the "
        "patch level version of the foreign Python interpreter. To remedy this you should use a "
        "3-component dotted version for PYVER. If your resolves fail due to more esoteric "
        "undefined environment markers, you should switch to specifying `complete_platforms` "
        "instead."
    )


class PexCompletePlatformsField(SpecialCasedDependencies):
    alias = "complete_platforms"
    help = (
        "The platforms the built PEX should be compatible with.\n\nThere must be built wheels "
        "available for all of the foreign platforms, rather than sdists.\n\n"
        "You can give a list of multiple complete platforms to create a multiplatform PEX, "
        "meaning that the PEX will be executable in all of the supported environments.\n\n"
        "Complete platforms should be addresses of `file` targets that point to files that contain "
        "complete platform JSON as described by Pex "
        "(https://pex.readthedocs.io/en/latest/buildingpex.html#complete-platform)."
    )


class PexInheritPathField(StringField):
    alias = "inherit_path"
    valid_choices = ("false", "fallback", "prefer")
    help = (
        "Whether to inherit the `sys.path` (aka PYTHONPATH) of the environment that the binary "
        "runs in.\n\nUse `false` to not inherit `sys.path`; use `fallback` to inherit `sys.path` "
        "after packaged dependencies; and use `prefer` to inherit `sys.path` before packaged "
        "dependencies."
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
    help = (
        "Whether or not to strip the PEX runtime environment of `PEX*` environment variables.\n\n"
        "Most applications have no need for the `PEX*` environment variables that are used to "
        "control PEX startup; so these variables are scrubbed from the environment by Pex before "
        "transferring control to the application by default. This prevents any subprocesses that "
        "happen to execute other PEX files from inheriting these control knob values since most "
        "would be undesired; e.g.: PEX_MODULE or PEX_PATH."
    )


class PexIgnoreErrorsField(BoolField):
    alias = "ignore_errors"
    default = False
    help = "Should PEX ignore when it cannot resolve dependencies?"


class PexShebangField(StringField):
    alias = "shebang"
    help = (
        "Set the generated PEX to use this shebang, rather than the default of PEX choosing a "
        "shebang based on the interpreter constraints.\n\nThis influences the behavior of running "
        "`./result.pex`. You can ignore the shebang by instead running "
        "`/path/to/python_interpreter ./result.pex`."
    )


class PexEmitWarningsField(TriBoolField):
    alias = "emit_warnings"
    help = (
        "Whether or not to emit PEX warnings at runtime.\n\nThe default is determined by the "
        "option `emit_warnings` in the `[pex-binary-defaults]` scope."
    )

    def value_or_global_default(self, pex_binary_defaults: PexBinaryDefaults) -> bool:
        if self.value is None:
            return pex_binary_defaults.emit_warnings
        return self.value


class PexResolveLocalPlatformsField(TriBoolField):
    alias = "resolve_local_platforms"
    help = (
        f"For each of the `{PexPlatformsField.alias}` specified, attempt to find a local "
        "interpreter that matches.\n\nIf a matching interpreter is found, use the interpreter to "
        "resolve distributions and build any that are only available in source distribution form. "
        "If no matching interpreter is found (or if this option is `False`), resolve for the "
        "platform by accepting only pre-built binary distributions (wheels)."
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
    help = (
        "The mode the generated PEX file will run in.\n\nThe traditional PEX file runs in a "
        f"modified {PexExecutionMode.ZIPAPP.value!r} mode (See: "
        "https://www.python.org/dev/peps/pep-0441/) where zipped internal code and dependencies "
        "are first unpacked to disk. This mode achieves the fastest cold start times and may, for "
        "example be the best choice for cloud lambda functions.\n\nThe fastest execution mode in "
        f"the steady state is {PexExecutionMode.VENV.value!r}, which generates a virtual "
        "environment from the PEX file on first run, but then achieves near native virtual "
        "environment start times. This mode also benefits from a traditional virtual environment "
        "`sys.path`, giving maximum compatibility with stdlib and third party APIs."
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
    help = (
        "The layout used for the PEX binary.\n\nBy default, a PEX is created as a single file "
        "zipapp, but either a packed or loose directory tree based layout can be chosen instead."
        "\n\nA packed layout PEX is an executable directory structure designed to have "
        "cache-friendly characteristics for syncing incremental updates to PEXed applications over "
        "a network. At the top level of the packed directory tree there is an executable "
        "`__main__.py` script. The directory can also be executed by passing its path to a Python "
        "executable; e.g: `python packed-pex-dir/`. The Pex bootstrap code and all dependency code "
        "are packed into individual zip files for efficient caching and syncing.\n\nA loose layout "
        "PEX is similar to a packed PEX, except that neither the Pex bootstrap code nor the "
        "dependency code are packed into zip files, but are instead present as collections of "
        "loose files in the directory tree providing different caching and syncing tradeoffs.\n\n"
        "Both zipapp and packed layouts install themselves in the `$PEX_ROOT` as loose apps by "
        "default before executing, but these layouts compose with "
        f"`{PexExecutionModeField.alias}='{PexExecutionMode.ZIPAPP.value}'` as well."
    )


class PexIncludeRequirementsField(BoolField):
    alias = "include_requirements"
    default = True
    help = (
        "Whether to include the third party requirements the binary depends on in the "
        "packaged PEX file."
    )


class PexIncludeToolsField(BoolField):
    alias = "include_tools"
    default = False
    help = (
        "Whether to include Pex tools in the PEX bootstrap code.\n\nWith tools included, the "
        "generated PEX file can be executed with `PEX_TOOLS=1 <pex file> --help` to gain access "
        "to all the available tools."
    )


_PEX_BINARY_COMMON_FIELDS = (
    InterpreterConstraintsField,
    PythonResolveField,
    PexBinaryDependenciesField,
    PexPlatformsField,
    PexCompletePlatformsField,
    PexResolveLocalPlatformsField,
    PexInheritPathField,
    PexStripEnvField,
    PexIgnoreErrorsField,
    PexShebangField,
    PexEmitWarningsField,
    PexLayoutField,
    PexExecutionModeField,
    PexIncludeRequirementsField,
    PexIncludeToolsField,
    RestartableField,
)


class PexBinary(Target):
    alias = "pex_binary"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        *_PEX_BINARY_COMMON_FIELDS,
        PexEntryPointField,
        PexScriptField,
        OutputPathField,
    )
    help = (
        "A Python target that can be converted into an executable PEX file.\n\nPEX files are "
        "self-contained executable files that contain a complete Python environment capable of "
        f"running the target. For more information, see {doc_url('pex-files')}."
    )

    def validate(self) -> None:
        if self[PexEntryPointField].value is not None and self[PexScriptField].value is not None:
            raise InvalidTargetException(
                f"The `{self.alias}` target {self.address} cannot set both the "
                f"`{self[PexEntryPointField].alias}` and `{self[PexScriptField].alias}` fields at "
                "the same time. To fix, please remove one."
            )


class PexEntryPointsField(StringSequenceField, AsyncFieldMixin):
    alias = "entry_points"
    default = None
    help = (
        "The entry points for each binary, i.e. what gets run when when executing `./my_app.pex.`"
        "\n\n"
        "Use a file name, relative to the BUILD file, like `app.py`. You can also set the "
        "function to run, like `app.py:func`. Pants will convert these file names into well-formed "
        "entry points, like `app.py:func` into `path.to.app:func.`"
        "\n\n"
        "If you want the entry point to be for a third-party dependency or to use a console "
        "script, use the `pex_binary` target directly."
    )


class PexBinariesOverrideField(OverridesField):
    help = (
        f"Override the field values for generated `{PexBinary.alias}` targets.\n\n"
        "Expects a dictionary mapping values from the `entry_points` field to a dictionary for "
        "their overrides. You may either use a single string or a tuple of strings to override "
        "multiple targets.\n\n"
        "For example:\n\n```\n"
        "overrides={\n"
        '  "foo.py": {"execution_mode": "venv"]},\n'
        '  "bar.py:main": {"restartable": True]},\n'
        '  ("foo.py", "bar.py:main"): {"tags": ["legacy"]},\n'
        "}"
        "\n```\n\n"
        "Every key is validated to belong to this target's `entry_points` field.\n\n"
        f"If you'd like to override a field's value for every `{PexBinary.alias}` target "
        "generated by this target, change the field directly on this target rather than using the "
        "`overrides` field.\n\n"
        "You can specify the same entry_point in multiple keys, so long as you don't override the "
        "same field more than one time for the entry_point."
    )


class PexBinariesGeneratorTarget(TargetGenerator):
    alias = "pex_binaries"
    help = (
        "Generate a `pex_binary` target for each entry_point in the `entry_points` field."
        "\n\n"
        "This is solely meant to reduce duplication when you have multiple scripts in the same "
        "directory; it's valid to use a distinct `pex_binary` target for each script/binary "
        "instead."
        "\n\n"
        "This target generator does not work well to generate `pex_binary` targets where the entry "
        "point is for a third-party dependency. Dependency inference will not work for those, so "
        "you will have to set lots of custom metadata for each binary; prefer an explicit "
        "`pex_binary` target in that case. This target generator works best when the entry point "
        "is a first-party file, like `app.py` or `app.py:main`."
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
        "--emit-warnings",
        default=True,
        help=(
            "Whether built PEX binaries should emit PEX warnings at runtime by default."
            "\n\nCan be overridden by specifying the `emit_warnings` parameter of individual "
            "`pex_binary` targets"
        ),
        advanced=True,
    )
    resolve_local_platforms = BoolOption(
        "--resolve-local-platforms",
        default=False,
        help=(
            f"For each of the `{PexPlatformsField.alias}` specified for a `{PexBinary.alias}` "
            "target, attempt to find a local interpreter that matches.\n\nIf a matching "
            "interpreter is found, use the interpreter to resolve distributions and build any "
            "that are only available in source distribution form. If no matching interpreter "
            "is found (or if this option is `False`), resolve for the platform by accepting "
            "only pre-built binary distributions (wheels)."
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
                f"The {repr(self.alias)} field in target {self.address} should not be set to the "
                f"file 'conftest.py', but was set to {repr(self.value)}.\n\nInstead, use a "
                "`python_source` target or the target generator `python_test_utils`. You can run "
                f"`{bin_name()} tailor` after removing this target ({self.address}) to autogenerate a "
                "`python_test_utils` target."
            )


class PythonTestsDependenciesField(Dependencies):
    supports_transitive_excludes = True


class PythonTestsTimeoutField(IntField):
    alias = "timeout"
    help = (
        "A timeout (in seconds) used by each test file belonging to this target.\n\n"
        "If unset, will default to `[pytest].timeout_default`; if that option is also unset, "
        "then the test will never time out. Will never exceed `[pytest].timeout_maximum`. Only "
        "applies if the option `--pytest-timeouts` is set to true (the default)."
    )
    valid_numbers = ValidNumbers.positive_only

    def calculate_from_global_options(self, pytest: PyTest) -> Optional[int]:
        """Determine the timeout (in seconds) after applying global `pytest` options."""
        if not pytest.timeouts_enabled:
            return None
        if self.value is None:
            if pytest.timeout_default is None:
                return None
            result = pytest.timeout_default
        else:
            result = self.value
        if pytest.timeout_maximum is not None:
            return min(result, pytest.timeout_maximum)
        return result


class PythonTestsExtraEnvVarsField(StringSequenceField):
    alias = "extra_env_vars"
    help = (
        "Additional environment variables to include in test processes. "
        "Entries are strings in the form `ENV_VAR=value` to use explicitly; or just "
        "`ENV_VAR` to copy the value of a variable in Pants's own environment. "
        "This will be merged with and override values from [test].extra_env_vars."
    )


class SkipPythonTestsField(BoolField):
    alias = "skip_tests"
    default = False
    help = "If true, don't run this target's tests."


_PYTHON_TEST_MOVED_FIELDS = (
    *COMMON_TARGET_FIELDS,
    PythonTestsDependenciesField,
    PythonResolveField,
    PythonTestsTimeoutField,
    RuntimePackageDependenciesField,
    PythonTestsExtraEnvVarsField,
    InterpreterConstraintsField,
    SkipPythonTestsField,
)


class PythonTestTarget(Target):
    alias = "python_test"
    core_fields = (*_PYTHON_TEST_MOVED_FIELDS, PythonTestsDependenciesField, PythonTestSourceField)
    help = (
        "A single Python test file, written in either Pytest style or unittest style.\n\n"
        "All test util code, including `conftest.py`, should go into a dedicated `python_source` "
        "target and then be included in the `dependencies` field. (You can use the "
        "`python_test_utils` target to generate these `python_source` targets.)\n\n"
        f"See {doc_url('python-test-goal')}"
    )


class PythonTestsGeneratingSourcesField(PythonGeneratingSourcesBase):
    expected_file_extensions = (".py", "")  # Note that this does not include `.pyi`.
    default = ("test_*.py", "*_test.py", "tests.py")

    def validate_resolved_files(self, files: Sequence[str]) -> None:
        super().validate_resolved_files(files)
        # We don't technically need to error for `conftest.py` here because `PythonTestSourceField`
        # already validates this, but we get a better error message this way so that users don't
        # have to reason about generated targets.
        conftest_files = [fp for fp in files if os.path.basename(fp) == "conftest.py"]
        if conftest_files:
            raise InvalidFieldException(
                f"The {repr(self.alias)} field in target {self.address} should not include the "
                f"file 'conftest.py', but included these: {conftest_files}.\n\nInstead, use a "
                "`python_source` target or the target generator `python_test_utils`. You can run "
                f"`{bin_name()} tailor` after removing the files from the {repr(self.alias)} field of "
                f"this target ({self.address}) to autogenerate a `python_test_utils` target."
            )


class PythonTestsOverrideField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        PythonTestTarget.alias,
        (
            "overrides={\n"
            '  "foo_test.py": {"timeout": 120]},\n'
            '  "bar_test.py": {"timeout": 200]},\n'
            '  ("foo_test.py", "bar_test.py"): {"tags": ["slow_tests"]},\n'
            "}"
        ),
    )


class PythonTestsGeneratorTarget(TargetFilesGenerator):
    alias = "python_tests"
    core_fields = (PythonTestsGeneratingSourcesField, PythonTestsOverrideField)
    generated_target_cls = PythonTestTarget
    copied_fields = ()
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
        Dependencies,
        PythonResolveField,
        PythonSourceField,
    )
    help = "A single Python source file."


class PythonSourcesOverridesField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        PythonSourceTarget.alias,
        (
            "overrides={\n"
            '  "foo.py": {"skip_pylint": True]},\n'
            '  "bar.py": {"skip_flake8": True]},\n'
            '  ("foo.py", "bar.py"): {"tags": ["linter_disabled"]},\n'
            "}"
        ),
    )


class PythonTestUtilsGeneratingSourcesField(PythonGeneratingSourcesBase):
    default = ("conftest.py", "test_*.pyi", "*_test.pyi", "tests.pyi")


class PythonSourcesGeneratingSourcesField(PythonGeneratingSourcesBase):
    default = (
        ("*.py", "*.pyi")
        + tuple(f"!{pat}" for pat in PythonTestsGeneratingSourcesField.default)
        + tuple(f"!{pat}" for pat in PythonTestUtilsGeneratingSourcesField.default)
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
    moved_fields = (PythonResolveField, Dependencies, InterpreterConstraintsField)
    settings_request_cls = PythonFilesGeneratorSettingsRequest
    help = (
        "Generate a `python_source` target for each file in the `sources` field.\n\n"
        "This target generator is intended for test utility files like `conftest.py` or "
        "`my_test_utils.py`. Technically, it generates `python_source` targets in the exact same "
        "way as the `python_sources` target generator does, only that the `sources` field has a "
        "different default. So it is valid to use `python_sources` instead. However, this target "
        "can be helpful to better model your code by keeping separate test support files vs. "
        "production files."
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
    moved_fields = (PythonResolveField, Dependencies, InterpreterConstraintsField)
    settings_request_cls = PythonFilesGeneratorSettingsRequest
    help = (
        "Generate a `python_source` target for each file in the `sources` field.\n\n"
        "You can either use this target generator or `python_test_utils` for test utility files "
        "like `conftest.py`. They behave identically, but can help to better model and keep "
        "separate test support files vs. production files."
    )


# -----------------------------------------------------------------------------------------------
# `python_requirement` target
# -----------------------------------------------------------------------------------------------


def format_invalid_requirement_string_error(
    value: str, e: Exception, *, description_of_origin: str
) -> str:
    prefix = f"Invalid requirement '{value}' in {description_of_origin}: {e}"
    # We check if they're using Pip-style VCS requirements, and redirect them to instead use PEP
    # 440 direct references. See https://pip.pypa.io/en/stable/reference/pip_install/#vcs-support.
    recognized_vcs = {"git", "hg", "svn", "bzr"}
    if all(f"{vcs}+" not in value for vcs in recognized_vcs):
        return prefix
    return dedent(
        f"""\
        {prefix}

        It looks like you're trying to use a pip VCS-style requirement?
        Instead, use a direct reference (PEP 440).

        Instead of this style:

            git+https://github.com/django/django.git#egg=Django
            git+https://github.com/django/django.git@stable/2.1.x#egg=Django
            git+https://github.com/django/django.git@fd209f62f1d83233cc634443cfac5ee4328d98b8#egg=Django

        Use this style, where the first value is the name of the dependency:

            Django@ git+https://github.com/django/django.git
            Django@ git+https://github.com/django/django.git@stable/2.1.x
            Django@ git+https://github.com/django/django.git@fd209f62f1d83233cc634443cfac5ee4328d98b8
        """
    )


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
                    parsed = PipRequirement.parse(v)
                except Exception as e:
                    raise InvalidFieldException(
                        format_invalid_requirement_string_error(
                            v,
                            e,
                            description_of_origin=(
                                f"the '{cls.alias}' field for the target {address}"
                            ),
                        )
                    )
                result.append(parsed)
            else:
                raise invalid_type_error
        return tuple(result)


class PythonRequirementsField(_PipRequirementSequenceField):
    alias = "requirements"
    required = True
    help = (
        'A pip-style requirement string, e.g. `["Django==3.2.8"]`.\n\n'
        "You can specify multiple requirements for the same project in order to use environment "
        'markers, such as `["foo>=1.2,<1.3 ; python_version>\'3.6\'", "foo==0.9 ; '
        "python_version<'3'\"]`.\n\n"
        "If the requirement depends on some other requirement to work, such as needing "
        "`setuptools` to be built, use the `dependencies` field instead."
    )


_default_module_mapping_url = git_url(
    "src/python/pants/backend/python/dependency_inference/default_module_mapping.py"
)


class PythonRequirementModulesField(StringSequenceField):
    alias = "modules"
    help = (
        "The modules this requirement provides (used for dependency inference).\n\n"
        'For example, the requirement `setuptools` provides `["setuptools", "pkg_resources", '
        '"easy_install"]`.\n\n'
        "Usually you can leave this field off. If unspecified, Pants will first look at the "
        f"default module mapping ({_default_module_mapping_url}), and then will default to "
        "the normalized project name. For example, the requirement `Django` would default to "
        "the module `django`.\n\n"
        "Mutually exclusive with the `type_stub_modules` field."
    )


class PythonRequirementTypeStubModulesField(StringSequenceField):
    alias = "type_stub_modules"
    help = (
        "The modules this requirement provides if the requirement is a type stub (used for "
        "dependency inference).\n\n"
        'For example, the requirement `types-requests` provides `["requests"]`.\n\n'
        "Usually you can leave this field off. If unspecified, Pants will first look at the "
        f"default module mapping ({_default_module_mapping_url}). If not found _and_ the "
        "requirement name starts with `types-` or `stubs-`, or ends with `-types` or `-stubs`, "
        "will default to that requirement name without the prefix/suffix. For example, "
        "`types-requests` would default to `requests`. Otherwise, will be treated like a normal "
        "requirement (see the `modules` field).\n\n"
        "Mutually exclusive with the `modules` field."
    )


def normalize_module_mapping(
    mapping: Mapping[str, Iterable[str]] | None
) -> FrozenDict[str, tuple[str, ...]]:
    return FrozenDict({canonicalize_project_name(k): tuple(v) for k, v in (mapping or {}).items()})


class PythonRequirementResolveField(PythonResolveField):
    alias = "resolve"
    required = False
    help = (
        "The resolve from `[python].resolves` that this requirement is included in.\n\n"
        "If not defined, will default to `[python].default_resolve`.\n\n"
        "When generating a lockfile for a particular resolve via the `generate-lockfiles` goal, "
        "it will include all requirements that are declared with that resolve. "
        "First-party targets like `python_source` and `pex_binary` then declare which resolve "
        "they use via their `resolve` field; so, for your first-party code to use a "
        "particular `python_requirement` target, that requirement must be included in the resolve "
        "used by that code."
    )


class PythonRequirementTarget(Target):
    alias = "python_requirement"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        PythonRequirementsField,
        PythonRequirementModulesField,
        PythonRequirementTypeStubModulesField,
        PythonRequirementResolveField,
    )
    help = (
        "A Python requirement installable by pip.\n\n"
        "This target is useful when you want to declare Python requirements inline in a "
        "BUILD file. If you have a `requirements.txt` file already, you can instead use "
        "the target generator `python_requirements` to convert each "
        "requirement into a `python_requirement` target automatically. For Poetry, use "
        "`poetry_requirements`.\n\n"
        f"See {doc_url('python-third-party-dependencies')}."
    )

    def validate(self) -> None:
        if (
            self[PythonRequirementModulesField].value
            and self[PythonRequirementTypeStubModulesField].value
        ):
            raise InvalidTargetException(
                f"The `{self.alias}` target {self.address} cannot set both the "
                f"`{self[PythonRequirementModulesField].alias}` and "
                f"`{self[PythonRequirementTypeStubModulesField].alias}` fields at the same time. "
                "To fix, please remove one."
            )


def parse_requirements_file(content: str, *, rel_path: str) -> Iterator[PipRequirement]:
    """Parse all `PipRequirement` objects from a requirements.txt-style file.

    This will safely ignore any options starting with `--` and will ignore comments. Any pip-style
    VCS requirements will fail, with a helpful error message describing how to use PEP 440.
    """
    for i, line in enumerate(content.splitlines()):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        try:
            yield PipRequirement.parse(line)
        except Exception as e:
            raise ValueError(
                format_invalid_requirement_string_error(
                    line, e, description_of_origin=f"{rel_path} at line {i + 1}"
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
    expected_type_help = "setup_py(name='my-dist', **kwargs)"
    value: PythonArtifact
    required = True
    help = (
        "The setup.py kwargs for the external artifact built from this target.\n\nYou must define "
        "`name`. You can also set almost any keyword argument accepted by setup.py in the "
        "`setup()` function: "
        "(https://packaging.python.org/guides/distributing-packages-using-setuptools/#setup-args)."
        f"\n\nSee {doc_url('plugins-setup-py')} for how to write a plugin to "
        "dynamically generate kwargs."
    )

    @classmethod
    def compute_value(cls, raw_value: Optional[PythonArtifact], address: Address) -> PythonArtifact:
        return cast(PythonArtifact, super().compute_value(raw_value, address))


class PythonDistributionEntryPointsField(NestedDictStringToStringField, AsyncFieldMixin):
    alias = "entry_points"
    required = False
    help = (
        "Any entry points, such as `console_scripts` and `gui_scripts`.\n"
        "\n"
        "Specify as a nested dictionary, with a dictionary for each type of entry point, "
        "e.g. `console_scripts` vs. `gui_scripts`. Each dictionary maps the entry point name to "
        'either a setuptools entry point ("path.to.module:func") or a Pants target address to a '
        "pex_binary target.\n\n"
        + dedent(
            """\
            Example:

                entry_points={
                  "console_scripts": {
                    "my-script": "project.app:main",
                    "another-script": "project/subdir:pex_binary_tgt"
                  }
                }

            """
        )
        + "Note that Pants will assume that any value that either starts with `:` or has `/` in it, "
        "is a target address to a pex_binary target. Otherwise, it will assume it's a setuptools "
        "entry point as defined by "
        "https://packaging.python.org/specifications/entry-points/#entry-points-specification. Use "
        "`//` as a prefix for target addresses if you need to disambiguate.\n\n"
        + dedent(
            f"""\
            Pants will attempt to infer dependencies, which you can confirm by running:

                {bin_name()} dependencies <python_distribution target address>

            """
        )
    )


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


class GenerateSetupField(TriBoolField):
    alias = "generate_setup"
    required = False
    # The default behavior if this field is unspecified is controlled by the
    # --generate-setup-default option in the setup-py-generation scope.
    default = None

    help = (
        "Whether to generate setup information for this distribution, based on analyzing "
        "sources and dependencies. Set to False to use existing setup information, such as "
        "existing setup.py, setup.cfg, pyproject.toml files or similar."
    )


class LongDescriptionPathField(StringField):
    alias = "long_description_path"
    required = False

    help = (
        "Path to a file that will be used to fill the long_description field in setup.py.\n\n"
        "Path is relative to the build root.\n\n"
        "Alternatively, you can set the `long_description` in the `provides` field, but not both.\n\n"
        "This field won't automatically set `long_description_content_type` field for you. "
        "You have to specify this field yourself in the `provides` field."
    )


class PythonDistribution(Target):
    alias = "python_distribution"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        PythonDistributionDependenciesField,
        PythonDistributionEntryPointsField,
        PythonProvidesField,
        GenerateSetupField,
        WheelField,
        SDistField,
        WheelConfigSettingsField,
        SDistConfigSettingsField,
        LongDescriptionPathField,
    )
    help = (
        "A publishable Python setuptools distribution (e.g. an sdist or wheel).\n\nSee "
        f"{doc_url('python-distributions')}."
    )
