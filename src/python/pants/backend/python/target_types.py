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
from typing import Dict, Iterable, Iterator, Optional, Tuple, Union, cast

from packaging.utils import canonicalize_name as canonicalize_project_name
from pkg_resources import Requirement

from pants.backend.python.dependency_inference.default_module_mapping import DEFAULT_MODULE_MAPPING
from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.subsystems.pytest import PyTest
from pants.core.goals.package import OutputPathField
from pants.core.goals.test import RuntimePackageDependenciesField
from pants.engine.addresses import Address
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
    ProvidesField,
    ScalarField,
    SecondaryOwnerMixin,
    Sources,
    StringField,
    StringSequenceField,
    Target,
    TriBoolField,
)
from pants.option.subsystem import Subsystem
from pants.python.python_setup import PythonSetup
from pants.source.filespec import Filespec
from pants.util.docutil import bracketed_docs_url
from pants.util.frozendict import FrozenDict

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------------------------
# Common fields
# -----------------------------------------------------------------------------------------------


class PythonSources(Sources):
    # Note that Python scripts often have no file ending.
    expected_file_extensions = ("", ".py", ".pyi")


class InterpreterConstraintsField(StringSequenceField):
    alias = "interpreter_constraints"
    help = (
        "The Python interpreters this code is compatible with.\n\nEach element should be written "
        "in pip-style format, e.g. 'CPython==2.7.*' or 'CPython>=3.6,<4'. You can leave off "
        "`CPython` as a shorthand, e.g. '>=2.7' will be expanded to 'CPython>=2.7'.\n\nSpecify "
        "more than one element to OR the constraints, e.g. `['PyPy==3.7.*', 'CPython==3.7.*']` "
        "means either PyPy 3.7 _or_ CPython 3.7.\n\nIf the field is not set, it will default to "
        "the option `[python-setup].interpreter_constraints`.\n\nSee "
        f"{bracketed_docs_url('python-interpreter-compatibility')}."
    )

    def value_or_global_default(self, python_setup: PythonSetup) -> Tuple[str, ...]:
        """Return either the given `compatibility` field or the global interpreter constraints.

        If interpreter constraints are supplied by the CLI flag, return those only.
        """
        return python_setup.compatibility_or_constraints(self.value)


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
    help = (
        "The entry point for the binary, i.e. what gets run when executing `./my_binary.pex`.\n\n"
        "You can specify a full module like 'path.to.module' and 'path.to.module:func', or use a "
        "shorthand to specify a file name, using the same syntax as the `sources` field:\n\n  1) "
        "'app.py', Pants will convert into the module `path.to.app`;\n  2) 'app.py:func', Pants "
        "will convert into `path.to.app:func`.\n\nYou must use the file name shorthand for file "
        "arguments to work with this target.\n\nTo leave off an entry point, set to '<none>'."
    )
    required = True
    value: EntryPoint

    @classmethod
    def compute_value(cls, raw_value: Optional[str], address: Address) -> EntryPoint:
        value = super().compute_value(raw_value, address)
        if not isinstance(value, str):
            raise InvalidFieldTypeException(address, cls.alias, value, expected_type="a string")
        try:
            return EntryPoint.parse(value, provenance=f"for {address}")
        except ValueError as e:
            raise InvalidFieldException(str(e))

    @property
    def filespec(self) -> Filespec:
        if not self.value.module.endswith(".py"):
            return {"includes": []}
        full_glob = os.path.join(self.address.spec_path, self.value.module)
        return {"includes": [full_glob]}


# See `target_types_rules.py` for the `ResolvePexEntryPointRequest -> ResolvedPexEntryPoint` rule.
@dataclass(frozen=True)
class ResolvedPexEntryPoint:
    val: Optional[EntryPoint]


@dataclass(frozen=True)
class ResolvePexEntryPointRequest:
    """Determine the `entry_point` for a `pex_binary` after applying all syntactic sugar."""

    entry_point_field: PexEntryPointField


class PexPlatformsField(StringSequenceField):
    alias = "platforms"
    help = (
        "The platforms the built PEX should be compatible with.\n\nThis defaults to the current "
        "platform, but can be overridden to different platforms. You can give a list of multiple "
        "platforms to create a multiplatform PEX.\n\nTo use wheels for specific "
        "interpreter/platform tags, you can append them to the platform with hyphens like: "
        'PLATFORM-IMPL-PYVER-ABI (e.g. "linux_x86_64-cp-27-cp27mu", '
        '"macosx_10.12_x86_64-cp-36-cp36m"):\n\n  - PLATFORM: the host platform, e.g. '
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


class PexZipSafeField(BoolField):
    alias = "zip_safe"
    default = True
    help = (
        "Whether or not this binary is safe to run in compacted (zip-file) form.\n\nIf the PEX is "
        "not zip safe, it will be written to disk prior to execution. You may need to mark "
        "`zip_safe=False` if you're having issues loading your code."
    )


class PexAlwaysWriteCacheField(BoolField):
    alias = "always_write_cache"
    default = False
    help = (
        "Whether PEX should always write the .deps cache of the .pex file to disk or not. This "
        "can use less memory in RAM-constrained environments."
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
        "The mode the generated PEX file will run in.\n\nThe traditional PEX file runs in "
        f"{PexExecutionMode.ZIPAPP.value!r} mode (See: https://www.python.org/dev/peps/pep-0441/). "
        f"In general, faster cold start times can be attained using the "
        f"{PexExecutionMode.UNZIP.value!r} mode which also has the benefit of allowing standard "
        "use of `__file__` and filesystem APIs to access code and resources in the PEX.\n\nThe "
        f"fastest execution mode in the steady state is {PexExecutionMode.VENV.value!r}, which "
        "generates a virtual environment from the PEX file on first run, but then achieves near "
        "native virtual environment start times. This mode also benefits from a traditional "
        "virtual environment `sys.path`, giving maximum compatibility with stdlib and third party "
        "APIs."
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
        PexBinaryDependencies,
        PexEntryPointField,
        PexPlatformsField,
        PexInheritPathField,
        PexZipSafeField,
        PexAlwaysWriteCacheField,
        PexIgnoreErrorsField,
        PexShebangField,
        PexEmitWarningsField,
        PexExecutionModeField,
        PexIncludeToolsField,
    )
    help = (
        "A Python target that can be converted into an executable PEX file.\n\nPEX files are "
        "self-contained executable files that contain a complete Python environment capable of "
        f"running the target. For more information, see {bracketed_docs_url('pex-files')}."
    )


# -----------------------------------------------------------------------------------------------
# `python_tests` target
# -----------------------------------------------------------------------------------------------


class PythonTestsSources(PythonSources):
    default = (
        "test_*.py",
        "*_test.py",
        "tests.py",
        "conftest.py",
        "test_*.pyi",
        "*_test.pyi",
        "tests.pyi",
    )


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


class PythonTests(Target):
    alias = "python_tests"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        InterpreterConstraintsField,
        PythonTestsSources,
        PythonTestsDependencies,
        PythonTestsTimeout,
        RuntimePackageDependenciesField,
        PythonTestsExtraEnvVars,
    )
    help = (
        "Python tests, written in either Pytest style or unittest style.\n\nAll test util code, "
        "other than `conftest.py`, should go into a dedicated `python_library()` target and then "
        f"be included in the `dependencies` field.\n\nSee {bracketed_docs_url('python-test-goal')}."
    )


# -----------------------------------------------------------------------------------------------
# `python_library` target
# -----------------------------------------------------------------------------------------------


class PythonLibrarySources(PythonSources):
    default = ("*.py", "*.pyi") + tuple(f"!{pat}" for pat in PythonTestsSources.default)


class PythonLibrary(Target):
    alias = "python_library"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        InterpreterConstraintsField,
        Dependencies,
        PythonLibrarySources,
    )
    help = (
        "Python source code.\n\nA `python_library` does not necessarily correspond to a "
        "distribution you publish (see `python_distribution` and `pex_binary` for that); multiple "
        "`python_library` targets may be packaged into a distribution or binary."
    )


# -----------------------------------------------------------------------------------------------
# `python_requirement_library` target
# -----------------------------------------------------------------------------------------------


def _format_invalid_requirement_string_error(
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
                        _format_invalid_requirement_string_error(
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
        "A sequence of pip-style requirement strings, e.g. `['foo==1.8', "
        "\"bar<=3 ; python_version<'3'\"]`."
    )


class ModuleMappingField(DictStringToStringSequenceField):
    alias = "module_mapping"
    help = (
        "A mapping of requirement names to a list of the modules they provide.\n\nFor example, "
        '`{"ansicolors": ["colors"]}`. Any unspecified requirements will use the requirement '
        'name as the default module, e.g. "Django" will default to `["django"]`.\n\nThis is '
        "used to infer dependencies."
    )
    value: FrozenDict[str, Tuple[str, ...]]

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Dict[str, Iterable[str]]], address: Address
    ) -> FrozenDict[str, Tuple[str, ...]]:
        provided_mapping = super().compute_value(raw_value, address)
        return FrozenDict(
            {
                **DEFAULT_MODULE_MAPPING,
                **{canonicalize_project_name(k): v for k, v in (provided_mapping or {}).items()},
            }
        )


class PythonRequirementLibrary(Target):
    alias = "python_requirement_library"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, PythonRequirementsField, ModuleMappingField)
    help = (
        "Python requirements installable by pip.\n\nThis target is useful when you want to declare "
        "Python requirements inline in a BUILD file. If you have a `requirements.txt` file "
        "already, you can instead use the macro `python_requirements()` to convert each "
        "requirement into a `python_requirement_library()` target automatically.\n\nSee "
        f"{bracketed_docs_url('python-third-party-dependencies')}."
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
                _format_invalid_requirement_string_error(
                    line, e, description_of_origin=f"{rel_path} at line {i + 1}"
                )
            )


class PythonRequirementsFileSources(Sources):
    required = True
    uses_source_roots = False


class PythonRequirementsFile(Target):
    alias = "_python_requirements_file"
    core_fields = (*COMMON_TARGET_FIELDS, PythonRequirementsFileSources)
    help = "A private helper target type for requirements.txt files."


# -----------------------------------------------------------------------------------------------
# `_python_constraints` target
# -----------------------------------------------------------------------------------------------


class PythonRequirementConstraintsField(_RequirementSequenceField):
    alias = "constraints"
    required = True
    help = "A list of pip-style requirement strings, e.g. `my_dist==4.2.1`."


class PythonRequirementConstraints(Target):
    alias = "_python_constraints"
    core_fields = (*COMMON_TARGET_FIELDS, PythonRequirementConstraintsField)
    help = "A private helper target for inlined requirements constraints, used by macros."


# -----------------------------------------------------------------------------------------------
# `python_distribution` target
# -----------------------------------------------------------------------------------------------


# See `target_types_rules.py` for a dependency injection rule.
class PythonDistributionDependencies(Dependencies):
    supports_transitive_excludes = True


class PythonProvidesField(ScalarField, ProvidesField):
    expected_type = PythonArtifact
    expected_type_help = "setup_py(name='my-dist', **kwargs)"
    value: PythonArtifact
    required = True
    help = (
        "The setup.py kwargs for the external artifact built from this target.\n\nSee "
        f"{bracketed_docs_url('python-distributions')}."
    )

    @classmethod
    def compute_value(cls, raw_value: Optional[PythonArtifact], address: Address) -> PythonArtifact:
        return cast(PythonArtifact, super().compute_value(raw_value, address))


class SetupPyCommandsField(StringSequenceField):
    alias = "setup_py_commands"
    expected_type_help = (
        "an iterable of string commands to invoke setup.py with, or "
        "an empty list to just create a chroot with a setup() function."
    )
    help = (
        "The runtime commands to invoke setup.py with to create the distribution, e.g. "
        '["bdist_wheel", "--python-tag=py36.py37", "sdist"].\n\nIf empty or unspecified, '
        "will just create a chroot with a setup() function.\n\nSee "
        f"{bracketed_docs_url('python-distributions')}."
    )


class PythonDistribution(Target):
    alias = "python_distribution"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        PythonDistributionDependencies,
        PythonProvidesField,
        SetupPyCommandsField,
    )
    help = "A publishable Python setuptools distribution (e.g. an sdist or wheel)."
