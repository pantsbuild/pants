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
    Any,
    ClassVar,
    Dict,
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
from pkg_resources import Requirement

from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.subsystems.setup import PythonSetup
from pants.base.deprecated import warn_or_error
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
    ProvidesField,
    ScalarField,
    SecondaryOwnerMixin,
    SingleSourceField,
    StringField,
    StringSequenceField,
    Target,
    TriBoolField,
    generate_file_based_overrides_field_help_message,
)
from pants.option.subsystem import Subsystem
from pants.source.filespec import Filespec
from pants.util.docutil import doc_url, git_url
from pants.util.frozendict import FrozenDict

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pants.backend.python.subsystems.pytest import PyTest


# -----------------------------------------------------------------------------------------------
# Common fields
# -----------------------------------------------------------------------------------------------


class PythonSourceField(SingleSourceField):
    # Note that Python scripts often have no file ending.
    expected_file_extensions = ("", ".py", ".pyi")


class PythonGeneratingSourcesBase(MultipleSourcesField):
    expected_file_extensions = ("", ".py", ".pyi")


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


class UnrecognizedResolveNamesError(Exception):
    def __init__(
        self,
        unrecognized_resolve_names: list[str],
        all_valid_names: Iterable[str],
        *,
        description_of_origin: str,
    ) -> None:
        # TODO(#12314): maybe implement "Did you mean?"
        if len(unrecognized_resolve_names) == 1:
            unrecognized_str = unrecognized_resolve_names[0]
            name_description = "name"
        else:
            unrecognized_str = str(sorted(unrecognized_resolve_names))
            name_description = "names"
        super().__init__(
            f"Unrecognized resolve {name_description} from {description_of_origin}: "
            f"{unrecognized_str}\n\nAll valid resolve names: {sorted(all_valid_names)}"
        )


class PythonResolveField(StringField, AsyncFieldMixin):
    alias = "experimental_resolve"
    # TODO(#12314): Figure out how to model the default and disabling lockfile, e.g. if we
    #  hardcode to `default` or let the user set it.
    help = (
        "The resolve from `[python].experimental_resolves_to_lockfiles` to use, if any.\n\n"
        "This field is highly experimental and may change without the normal deprecation policy."
    )

    def validate(self, python_setup: PythonSetup) -> None:
        """Check that the resolve name is recognized."""
        if not self.value:
            return None
        if self.value not in python_setup.resolves_to_lockfiles:
            raise UnrecognizedResolveNamesError(
                [self.value],
                python_setup.resolves_to_lockfiles.keys(),
                description_of_origin=f"the field `{self.alias}` in the target {self.address}",
            )

    def resolve_and_lockfile(self, python_setup: PythonSetup) -> tuple[str, str] | None:
        """If configured, return the resolve name with its lockfile.

        Error if the resolve name is invalid.
        """
        self.validate(python_setup)
        return (
            (self.value, python_setup.resolves_to_lockfiles[self.value])
            if self.value is not None
            else None
        )


# -----------------------------------------------------------------------------------------------
# `pex_binary` target
# -----------------------------------------------------------------------------------------------


class PexBinaryDefaults(Subsystem):
    options_scope = "pex-binary-defaults"
    help = "Default settings for creating PEX executables."

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--emit-warnings",
            advanced=True,
            type=bool,
            default=True,
            help=(
                "Whether built PEX binaries should emit PEX warnings at runtime by default."
                "\n\nCan be overridden by specifying the `emit_warnings` parameter of individual "
                "`pex_binary` targets"
            ),
        )

    @property
    def emit_warnings(self) -> bool:
        return cast(bool, self.options.emit_warnings)


# See `target_types_rules.py` for a dependency injection rule.
class PexBinaryDependencies(Dependencies):
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
        if value in {"<none>", "<None>"}:
            warn_or_error(
                "2.9.0.dev0",
                "using `<none>` for the `entry_point` field",
                (
                    "Rather than setting `entry_point='<none>' for the pex_binary target "
                    f"{address}, simply leave off the field."
                ),
            )
            return None
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
        "The platforms the built PEX should be compatible with.\n\nThis defaults to the current "
        "platform, but can be overridden to different platforms. There must be built wheels "
        "available for all of the foreign platforms, rather than sdists.\n\n"
        "You can give a list of multiple platforms to create a multiplatform PEX, "
        "meaning that the PEX will be executable in all of the supported environments.\n\n"
        "Platforms should be in the format defined by Pex "
        "(https://pex.readthedocs.io/en/latest/buildingpex.html#platform), i.e. "
        'PLATFORM-IMPL-PYVER-ABI (e.g. "linux_x86_64-cp-27-cp27mu", '
        '"macosx_10.12_x86_64-cp-36-cp36m"):\n\n'
        "  - PLATFORM: the host platform, e.g. "
        '"linux-x86_64", "macosx-10.12-x86_64".\n  - IMPL: the Python implementation '
        'abbreviation, e.g. "cp", "pp", "jp".\n  - PYVER: a two-digit string representing '
        'the Python version, e.g. "27", "36".\n  - ABI: the ABI tag, e.g. "cp36m", '
        '"cp27mu", "abi3", "none".'
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


# TODO(John Sirois): Deprecate: https://github.com/pantsbuild/pants/issues/12803
class PexZipSafeField(BoolField):
    alias = "zip_safe"
    default = True
    help = (
        "Whether or not this binary is safe to run in compacted (zip-file) form.\n\nIf the PEX is "
        "not zip safe, it will be written to disk prior to execution. You may need to mark "
        "`zip_safe=False` if you're having issues loading your code."
    )
    removal_version = "2.9.0.dev0"
    removal_hint = (
        "All PEX binaries now unpack your code to disk prior to first execution; so this option no "
        "longer needs to be specified."
    )


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


class PexAlwaysWriteCacheField(BoolField):
    alias = "always_write_cache"
    default = False
    help = (
        "Whether PEX should always write the .deps cache of the .pex file to disk or not. This "
        "can use less memory in RAM-constrained environments."
    )
    removal_version = "2.9.0.dev0"
    removal_hint = (
        "This option never had any effect when passed to Pex and the Pex option is now removed "
        "altogether. PEXes always write all their internal dependencies out to disk as part of "
        "first execution bootstrapping."
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


class PexExecutionMode(Enum):
    ZIPAPP = "zipapp"
    UNZIP = "unzip"
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
        "`sys.path`, giving maximum compatibility with stdlib and third party APIs.\n\nThe "
        f"{PexExecutionMode.UNZIP.value!r} mode is deprecated since the default "
        f"{PexExecutionMode.ZIPAPP.value!r} mode now executes this way."
    )

    @classmethod
    def _check_deprecated(cls, raw_value: Optional[Any], address_: Address) -> None:
        if PexExecutionMode.UNZIP.value == raw_value:
            warn_or_error(
                removal_version="2.9.0.dev0",
                entity=f"the {cls.alias!r} field {PexExecutionMode.UNZIP.value!r} value",
                hint=(
                    f"The {PexExecutionMode.UNZIP.value!r} mode is now the default PEX execution "
                    "mode; so you can remove this field setting or explicitly choose the default "
                    f"of {PexExecutionMode.ZIPAPP.value!r} and get the same benefits you already "
                    "enjoy from this mode."
                ),
            )


class PexIncludeToolsField(BoolField):
    alias = "include_tools"
    default = False
    help = (
        "Whether to include Pex tools in the PEX bootstrap code.\n\nWith tools included, the "
        "generated PEX file can be executed with `PEX_TOOLS=1 <pex file> --help` to gain access "
        "to all the available tools."
    )


class PexBinary(Target):
    alias = "pex_binary"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        OutputPathField,
        InterpreterConstraintsField,
        PythonResolveField,
        PexBinaryDependencies,
        PexEntryPointField,
        PexScriptField,
        PexPlatformsField,
        PexInheritPathField,
        PexZipSafeField,
        PexStripEnvField,
        PexAlwaysWriteCacheField,
        PexIgnoreErrorsField,
        PexShebangField,
        PexEmitWarningsField,
        PexExecutionModeField,
        PexIncludeToolsField,
        RestartableField,
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


# -----------------------------------------------------------------------------------------------
# `python_test` and `python_tests` targets
# -----------------------------------------------------------------------------------------------


# TODO(#13238): Update this to ban `.pyi` file extensions and ban `conftest.py` with a helpful
#  message to use `python_source`/`python_test_utils` instead.
class PythonTestSourceField(PythonSourceField):
    pass


class PythonTestsDependencies(Dependencies):
    supports_transitive_excludes = True


class PythonTestsTimeout(IntField):
    alias = "timeout"
    help = (
        "A timeout (in seconds) used by each test file belonging to this target.\n\n"
        "This only applies if the option `--pytest-timeouts` is set to True."
    )

    @classmethod
    def compute_value(cls, raw_value: Optional[int], address: Address) -> Optional[int]:
        value = super().compute_value(raw_value, address)
        if value is not None and value < 1:
            raise InvalidFieldException(
                f"The value for the `timeout` field in target {address} must be > 0, but was "
                f"{value}."
            )
        return value

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


class PythonTestsExtraEnvVars(StringSequenceField):
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


_PYTHON_TEST_COMMON_FIELDS = (
    *COMMON_TARGET_FIELDS,
    InterpreterConstraintsField,
    PythonResolveField,
    PythonTestsDependencies,
    PythonTestsTimeout,
    RuntimePackageDependenciesField,
    PythonTestsExtraEnvVars,
    SkipPythonTestsField,
)


class PythonTestTarget(Target):
    alias = "python_test"
    core_fields = (*_PYTHON_TEST_COMMON_FIELDS, PythonTestSourceField)
    help = (
        "A single Python test file, written in either Pytest style or unittest style.\n\n"
        "All test util code, including `conftest.py`, should go into a dedicated `python_source` "
        "target and then be included in the `dependencies` field.\n\n"
        f"See {doc_url('python-test-goal')}"
    )


# TODO(#13238): Update this to ban `.pyi` file extensions and ban `conftest.py` with a helpful
#  message to use `python_test_utils` instead.
class PythonTestsGeneratingSourcesField(PythonGeneratingSourcesBase):
    default = ("test_*.py", "*_test.py", "tests.py")

    def validate_resolved_files(self, files: Sequence[str]) -> None:
        super().validate_resolved_files(files)
        deprecated_files = []
        for fp in files:
            file_name = os.path.basename(fp)
            if file_name == "conftest.py" or file_name.endswith(".pyi"):
                deprecated_files.append(fp)

        if deprecated_files:
            # NOTE: Update `pytest.py` to stop special-casing file targets once this is removed!
            warn_or_error(
                "2.9.0.dev0",
                entity=(
                    "including `conftest.py` and `.pyi` stubs in a `python_tests` target's "
                    "`sources` field"
                ),
                hint=(
                    f"The `python_tests` target {self.address} includes these bad files in its "
                    f"`sources` field: {deprecated_files}. "
                    "To fix, please remove these files from the `sources` field and instead add "
                    "them to a `python_test_utils` target. You can run `./pants tailor` after "
                    "removing the files from the `sources` field to auto-generate this new target."
                ),
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


class PythonTestsGeneratorTarget(Target):
    alias = "python_tests"
    core_fields = (
        *_PYTHON_TEST_COMMON_FIELDS,
        PythonTestsGeneratingSourcesField,
        PythonTestsOverrideField,
    )
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


class PythonTestUtilsGeneratorTarget(Target):
    alias = "python_test_utils"
    # Keep in sync with `PythonSourcesGeneratorTarget`, outside of the `sources` field.
    core_fields = (
        *COMMON_TARGET_FIELDS,
        InterpreterConstraintsField,
        Dependencies,
        PythonTestUtilsGeneratingSourcesField,
        PythonSourcesOverridesField,
    )
    help = (
        "Generate a `python_source` target for each file in the `sources` field.\n\n"
        "This target generator is intended for test utility files like `conftest.py`, although it "
        "behaves identically to the `python_sources` target generator and you can safely use that "
        "instead. This target only exists to help you better model and keep separate test support "
        "files vs. production files."
    )


class PythonSourcesGeneratorTarget(Target):
    alias = "python_sources"
    # Keep in sync with `PythonTestUtilsGeneratorTarget`, outside of the `sources` field.
    core_fields = (
        *COMMON_TARGET_FIELDS,
        InterpreterConstraintsField,
        Dependencies,
        PythonSourcesGeneratingSourcesField,
        PythonSourcesOverridesField,
    )
    help = (
        "Generate a `python_source` target for each file in the `sources` field.\n\n"
        "You can either use this target generator or `python_test_utils` for test utility files "
        "like `conftest.py`. They behave identically, but can help to better model and keep "
        "separate test support files vs. production files."
    )

    deprecated_alias = "python_library"
    deprecated_alias_removal_version = "2.9.0.dev0"


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


class _RequirementSequenceField(Field):
    value: tuple[Requirement, ...]

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Iterable[str]], address: Address
    ) -> Tuple[Requirement, ...]:
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
            # We allow passing a pre-parsed `Requirement`. This is intended for macros which might
            # have already parsed so that we can avoid parsing multiple times.
            if isinstance(v, Requirement):
                result.append(v)
            elif isinstance(v, str):
                try:
                    parsed = Requirement.parse(v)
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


class PythonRequirementsField(_RequirementSequenceField):
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


class ModuleMappingField(DictStringToStringSequenceField):
    alias = "module_mapping"
    help = (
        "A mapping of requirement names to a list of the modules they provide.\n\n"
        'For example, `{"ansicolors": ["colors"]}`.\n\n'
        "Any unspecified requirements will use the requirement name as the default module, "
        'e.g. "Django" will default to `["django"]`.\n\n'
        "This is used to infer dependencies."
    )
    value: FrozenDict[str, tuple[str, ...]]
    default: ClassVar[FrozenDict[str, tuple[str, ...]]] = FrozenDict()
    removal_version = "2.9.0.dev0"
    removal_hint = (
        "Use the field `modules` instead, which takes a list of modules the `python_requirement` "
        "target provides.\n\n"
        "If this `python_requirement` target has multiple distinct 3rd-party "
        "projects in its `requirements` field, you should split those up into one `"
        "python_requirement` target per distinct project."
    )

    @classmethod
    def compute_value(  # type: ignore[override]
        cls, raw_value: Dict[str, Iterable[str]], address: Address
    ) -> FrozenDict[str, Tuple[str, ...]]:
        value_or_default = super().compute_value(raw_value, address)
        return normalize_module_mapping(value_or_default)


class TypeStubsModuleMappingField(DictStringToStringSequenceField):
    alias = "type_stubs_module_mapping"
    help = (
        "A mapping of type-stub requirement names to a list of the modules they provide.\n\n"
        'For example, `{"types-requests": ["requests"]}`.\n\n'
        "If the requirement is not specified _and_ it starts with `types-` or `stubs-`, or ends "
        "with `-types` or `-stubs`, the requirement will be treated as a type stub for the "
        'corresponding module, e.g. "types-request" has the module "requests". Otherwise, '
        "the requirement is treated like a normal dependency (see the field "
        f"{ModuleMappingField.alias}).\n\n"
        "This is used to infer dependencies for type stubs."
    )
    value: FrozenDict[str, tuple[str, ...]]
    default: ClassVar[FrozenDict[str, tuple[str, ...]]] = FrozenDict()
    removal_version = "2.9.0.dev0"
    removal_hint = (
        "Use the field `type_stub_modules` instead, which takes a list of modules the "
        "`python_requirement` target provides type stubs for.\n\n"
        "If this `python_requirement` target has multiple distinct 3rd-party "
        "projects in its `requirements` field, you should split those up into one `"
        "python_requirement` target per distinct project."
    )

    @classmethod
    def compute_value(  # type: ignore[override]
        cls, raw_value: Dict[str, Iterable[str]], address: Address
    ) -> FrozenDict[str, Tuple[str, ...]]:
        value_or_default = super().compute_value(raw_value, address)
        return normalize_module_mapping(value_or_default)


class PythonRequirementTarget(Target):
    alias = "python_requirement"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        PythonRequirementsField,
        PythonRequirementModulesField,
        PythonRequirementTypeStubModulesField,
        ModuleMappingField,
        TypeStubsModuleMappingField,
    )
    help = (
        "A Python requirement installable by pip.\n\n"
        "This target is useful when you want to declare Python requirements inline in a "
        "BUILD file. If you have a `requirements.txt` file already, you can instead use "
        "the macro `python_requirements()` to convert each "
        "requirement into a `python_requirement()` target automatically. For Poetry, use "
        "`poetry_requirements()`."
        "\n\n"
        f"See {doc_url('python-third-party-dependencies')}."
    )

    deprecated_alias = "python_requirement_library"
    deprecated_alias_removal_version = "2.9.0.dev0"

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


# -----------------------------------------------------------------------------------------------
# `_python_requirements_file` target
# -----------------------------------------------------------------------------------------------


def parse_requirements_file(content: str, *, rel_path: str) -> Iterator[Requirement]:
    """Parse all `Requirement` objects from a requirements.txt-style file.

    This will safely ignore any options starting with `--` and will ignore comments. Any pip-style
    VCS requirements will fail, with a helpful error message describing how to use PEP 440.
    """
    for i, line in enumerate(content.splitlines()):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        try:
            yield Requirement.parse(line)
        except Exception as e:
            raise ValueError(
                format_invalid_requirement_string_error(
                    line, e, description_of_origin=f"{rel_path} at line {i + 1}"
                )
            )


class PythonRequirementsFileSources(MultipleSourcesField):
    required = True
    uses_source_roots = False


class PythonRequirementsFile(Target):
    alias = "_python_requirements_file"
    core_fields = (*COMMON_TARGET_FIELDS, PythonRequirementsFileSources)
    help = "A private helper target type for requirements.txt files."


# -----------------------------------------------------------------------------------------------
# `python_distribution` target
# -----------------------------------------------------------------------------------------------


# See `target_types_rules.py` for a dependency injection rule.
class PythonDistributionDependencies(Dependencies):
    supports_transitive_excludes = True


class PythonProvidesField(ScalarField, ProvidesField, AsyncFieldMixin):
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
            """\
            Pants will attempt to infer dependencies, which you can confirm by running:

                ./pants dependencies <python_distribution target address>

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


class SetupPyCommandsField(StringSequenceField):
    removal_version = "2.9.0.dev0"
    removal_hint = "Set the boolean `wheel` and/or `sdist` fields instead."

    alias = "setup_py_commands"
    expected_type_help = (
        "an iterable of string commands to invoke setup.py with, or "
        "an empty list to just create a chroot with a setup() function."
    )
    help = (
        "The runtime commands to invoke setup.py with to create the distribution, e.g. "
        '["bdist_wheel", "--python-tag=py36.py37", "sdist"].\n\nIf empty or unspecified, '
        "will just create a chroot with a setup() function."
    )


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


class PythonDistribution(Target):
    alias = "python_distribution"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        PythonDistributionDependencies,
        PythonDistributionEntryPointsField,
        PythonProvidesField,
        GenerateSetupField,
        WheelField,
        SDistField,
        WheelConfigSettingsField,
        SDistConfigSettingsField,
        SetupPyCommandsField,
    )
    help = (
        "A publishable Python setuptools distribution (e.g. an sdist or wheel).\n\nSee "
        f"{doc_url('python-distributions')}."
    )
