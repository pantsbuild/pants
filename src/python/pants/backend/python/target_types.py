# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
from typing import Iterable, Optional, Sequence, Tuple, Union, cast

from pants.backend.python.python_artifact import PythonArtifact
from pants.backend.python.subsystems.pytest import PyTest
from pants.engine.addresses import Address
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    BoolField,
    Dependencies,
    IntField,
    InvalidFieldException,
    ProvidesField,
    ScalarField,
    SequenceField,
    Sources,
    StringField,
    StringOrStringSequenceField,
    Target,
)
from pants.python.python_requirement import PythonRequirement
from pants.python.python_setup import PythonSetup
from pants.subsystem.subsystem import Subsystem

# -----------------------------------------------------------------------------------------------
# Common fields
# -----------------------------------------------------------------------------------------------


class PythonSources(Sources):
    expected_file_extensions = (".py",)


class PythonInterpreterCompatibility(StringOrStringSequenceField):
    """A string for Python interpreter constraints on this target.

    This should be written in Requirement-style format, e.g. `CPython==2.7.*` or `CPython>=3.6,<4`.
    As a shortcut, you can leave off `CPython`, e.g. `>=2.7` will be expanded to `CPython>=2.7`.

    If this is left off, this will default to the option `interpreter_constraints` in the
    [python-setup] scope.

    See https://pants.readme.io/docs/python-interpreter-compatibility.
    """

    alias = "compatibility"

    def value_or_global_default(self, python_setup: PythonSetup) -> Tuple[str, ...]:
        """Return either the given `compatibility` field or the global interpreter constraints.

        If interpreter constraints are supplied by the CLI flag, return those only.
        """
        return python_setup.compatibility_or_constraints(self.value)


class PythonProvidesField(ScalarField, ProvidesField):
    """The`setup.py` kwargs for the external artifact built from this target.

    See https://pants.readme.io/docs/python-setup-py-goal.
    """

    expected_type = PythonArtifact
    expected_type_description = "setup_py(**kwargs)"
    value: Optional[PythonArtifact]

    @classmethod
    def compute_value(
        cls, raw_value: Optional[PythonArtifact], *, address: Address
    ) -> Optional[PythonArtifact]:
        return super().compute_value(raw_value, address=address)


COMMON_PYTHON_FIELDS = (
    *COMMON_TARGET_FIELDS,
    Dependencies,
    # TODO(#9388): Only register the Provides field on PythonBinary and PythonLibrary, not things
    #  like PythonTests.
    PythonProvidesField,
    PythonInterpreterCompatibility,
)


# -----------------------------------------------------------------------------------------------
# `python_binary` target
# -----------------------------------------------------------------------------------------------


class PythonBinaryDefaults(Subsystem):
    """Default settings for creating Python executables."""

    options_scope = "python-binary"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--pex-emit-warnings",
            advanced=True,
            type=bool,
            default=True,
            fingerprint=True,
            help=(
                "Whether built PEX binaries should emit pex warnings at runtime by default. "
                "Can be over-ridden by specifying the `emit_warnings` parameter of individual "
                "`python_binary` targets"
            ),
        )

    @property
    def pex_emit_warnings(self) -> bool:
        return cast(bool, self.options.pex_emit_warnings)


class PythonBinarySources(PythonSources):
    """A single file containing the executable, such as ['app.py'].

    You can leave this off if you include the executable file in one of this target's
    `dependencies` and explicitly set this target's `entry_point`.

    This must have 0 or 1 files, but no more. If you depend on more files, put them in a
    `python_library` target and include that target in the `dependencies` field.
    """

    expected_num_files = range(0, 2)

    @staticmethod
    def translate_source_file_to_entry_point(stripped_sources: Sequence[str]) -> Optional[str]:
        # We assume we have 0-1 sources, which is enforced by PythonBinarySources.
        if len(stripped_sources) != 1:
            return None
        module_base, _ = os.path.splitext(stripped_sources[0])
        return module_base.replace(os.path.sep, ".")


class PythonEntryPoint(StringField):
    """The default entry point for the binary.

    If omitted, Pants will use the module name from the `sources` field, e.g. `project/app.py` will
    become the entry point `project.app` .
    """

    alias = "entry_point"


class PythonPlatforms(StringOrStringSequenceField):
    """The platforms the built PEX should be compatible with.

    This defaults to the current platform, but can be overridden to different platforms. You can
    give a list of multiple platforms to create a multiplatform PEX.

    To use wheels for specific interpreter/platform tags, you can append them to the platform with
    hyphens like: PLATFORM-IMPL-PYVER-ABI (e.g. "linux_x86_64-cp-27-cp27mu",
    "macosx_10.12_x86_64-cp-36-cp36m"). PLATFORM is the host platform e.g. "linux-x86_64",
    "macosx-10.12-x86_64", etc". IMPL is the Python implementation abbreviation
    (e.g. "cp", "pp", "jp"). PYVER is a two-digit string representing the python version
    (e.g. "27", "36"). ABI is the ABI tag (e.g. "cp36m", "cp27mu", "abi3", "none").
    """

    alias = "platforms"


class PexInheritPath(StringField):
    """Whether to inherit the `sys.path` of the environment that the binary runs in.

    Use `false` to not inherit `sys.path`; use `fallback` to inherit `sys.path` after packaged
    dependencies; and use `prefer` to inherit `sys.path` before packaged dependencies.
    """

    alias = "inherit_path"
    valid_choices = ("false", "fallback", "prefer")

    # TODO(#9388): deprecate allowing this to be a `bool`.
    @classmethod
    def compute_value(
        cls, raw_value: Optional[Union[str, bool]], *, address: Address
    ) -> Optional[str]:
        if isinstance(raw_value, bool):
            return "prefer" if raw_value else "false"
        return super().compute_value(raw_value, address=address)


class PexZipSafe(BoolField):
    """Whether or not this binary is safe to run in compacted (zip-file) form.

    If they are not zip safe, they will be written to disk prior to execution.
    """

    alias = "zip_safe"
    default = True
    value: bool


class PexAlwaysWriteCache(BoolField):
    """Whether PEX should always write the .deps cache of the .pex file to disk or not.

    This can use less memory in RAM constrained environments.
    """

    alias = "always_write_cache"
    default = False
    value: bool


class PexIgnoreErrors(BoolField):
    """Should we ignore when PEX cannot resolve dependencies?"""

    alias = "ignore_errors"
    default = False
    value: bool


class PexShebang(StringField):
    """For the generated PEX, use this shebang."""

    alias = "shebang"


class PexEmitWarnings(BoolField):
    """Whether or not to emit PEX warnings at runtime.

    The default is determined by the option `pex_runtime_warnings` in the `[python-binary]` scope.
    """

    alias = "emit_warnings"

    def value_or_global_default(self, python_binary_defaults: PythonBinaryDefaults) -> bool:
        if self.value is None:
            return python_binary_defaults.pex_emit_warnings
        return self.value


class PythonBinary(Target):
    """A Python target that can be converted into an executable PEX file.

    PEX files are self-contained executable files that contain a complete Python environment capable
    of running the target. For more information about PEX files, see
    https://pants.readme.io/docs/pex-files.
    """

    alias = "python_binary"
    core_fields = (
        *COMMON_PYTHON_FIELDS,
        PythonBinarySources,
        PythonEntryPoint,
        PythonPlatforms,
        PexInheritPath,
        PexZipSafe,
        PexAlwaysWriteCache,
        PexIgnoreErrors,
        PexShebang,
        PexEmitWarnings,
    )


# -----------------------------------------------------------------------------------------------
# `python_tests` target
# -----------------------------------------------------------------------------------------------


class PythonTestsSources(PythonSources):
    default = ("test_*.py", "*_test.py", "tests.py", "conftest.py")


class PythonTestsTimeout(IntField):
    """A timeout (in seconds) which covers the total runtime of all tests in this target.

    This only applies if the option `--pytest-timeouts` is set to True.
    """

    alias = "timeout"

    @classmethod
    def compute_value(cls, raw_value: Optional[int], *, address: Address) -> Optional[int]:
        value = super().compute_value(raw_value, address=address)
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


class PythonTests(Target):
    """Python tests.

    These may be written in either Pytest-style or unittest style.

    See https://pants.readme.io/docs/python-test-goal.
    """

    alias = "python_tests"
    core_fields = (*COMMON_PYTHON_FIELDS, PythonTestsSources, PythonTestsTimeout)


# -----------------------------------------------------------------------------------------------
# `python_library` target
# -----------------------------------------------------------------------------------------------


class PythonLibrarySources(PythonSources):
    default = ("*.py",) + tuple(f"!{pat}" for pat in PythonTestsSources.default)


class PythonLibrary(Target):
    """A Python library that may be imported by other targets."""

    alias = "python_library"
    core_fields = (*COMMON_PYTHON_FIELDS, PythonLibrarySources)


# -----------------------------------------------------------------------------------------------
# `python_requirement_library` target
# -----------------------------------------------------------------------------------------------


class PythonRequirementsField(SequenceField):
    """A sequence of `python_requirement` objects.

    For example:

        requirements = [
            python_requirement('dep1==1.8'),
            python_requirement('dep2>=3.0,<3.1'),
        ]
    """

    alias = "requirements"
    expected_element_type = PythonRequirement
    expected_type_description = "an iterable of `python_requirement` objects (e.g. a list)"
    required = True
    value: Tuple[PythonRequirement, ...]

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Iterable[PythonRequirement]], *, address: Address
    ) -> Tuple[PythonRequirement, ...]:
        return cast(
            Tuple[PythonRequirement, ...], super().compute_value(raw_value, address=address)
        )


class PythonRequirementLibrary(Target):
    """A set of Pip requirements.

    This target is useful when you want to declare Python requirements inline in a BUILD file. If
    you have a `requirements.txt` file already, you can instead use the macro
    `python_requirements()` to convert each requirement into a `python_requirement_library()` target
    automatically.

    See https://pants.readme.io/docs/python-third-party-dependencies.
    """

    alias = "python_requirement_library"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, PythonRequirementsField)


# -----------------------------------------------------------------------------------------------
# `_python_requirements_file` target
# -----------------------------------------------------------------------------------------------


class PythonRequirementsFileSources(Sources):
    pass


class PythonRequirementsFile(Target):
    """A private, helper target type for requirements.txt files."""

    alias = "_python_requirements_file"
    core_fields = (*COMMON_TARGET_FIELDS, PythonRequirementsFileSources)
