# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
from typing import Iterable, Optional, Sequence, Tuple, Union, cast

from pants.backend.python.python_artifact import PythonArtifact
from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.targets.python_binary import PythonBinary as PythonBinaryV1
from pants.engine.addresses import Address
from pants.engine.fs import Snapshot
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    BoolField,
    BundlesField,
    Dependencies,
    IntField,
    InvalidFieldException,
    ProvidesField,
    ScalarField,
    SequenceField,
    Sources,
    StringField,
    StringOrStringSequenceField,
    StringSequenceField,
    Target,
)
from pants.fs.archive import TYPE_NAMES
from pants.python.python_requirement import PythonRequirement
from pants.python.python_setup import PythonSetup

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
# `python_app` target
# -----------------------------------------------------------------------------------------------


class PythonAppBinaryField(StringField):
    """Target spec of the `python_binary` that contains the app main."""

    alias = "binary"


class PythonAppBasename(StringField):
    """Name of this application, if different from the `name`.

    Pants uses this in the `bundle` goal to name the distribution artifact.
    """

    alias = "basename"


class PythonAppArchiveFormat(StringField):
    """Create an archive of this type from the bundle."""

    alias = "archive"
    valid_choices = tuple(sorted(TYPE_NAMES))


class PythonApp(Target):
    """A deployable Python application.

    Invoking the `bundle` goal on one of these targets creates a self-contained artifact suitable
    for deployment on some other machine. The artifact contains the executable PEX, its
    dependencies, and extra files like config files, startup scripts, etc.
    """

    alias = "python_app"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        BundlesField,
        PythonAppBinaryField,
        PythonAppBasename,
        PythonAppArchiveFormat,
    )
    v1_only = True


# -----------------------------------------------------------------------------------------------
# `python_binary` target
# -----------------------------------------------------------------------------------------------


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

    def value_or_global_default(self, python_binary_defaults: PythonBinaryV1.Defaults) -> bool:
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
# `python_library` target
# -----------------------------------------------------------------------------------------------


class PythonLibrarySources(PythonSources):
    default = ("*.py", "!test_*.py", "!*_test.py", "!conftest.py")


class PythonLibrary(Target):
    """A Python library that may be imported by other targets."""

    alias = "python_library"
    core_fields = (*COMMON_PYTHON_FIELDS, PythonLibrarySources)


# -----------------------------------------------------------------------------------------------
# `python_tests` target
# -----------------------------------------------------------------------------------------------


class PythonTestsSources(PythonSources):
    default = ("test_*.py", "*_test.py", "conftest.py")


class PythonCoverage(StringOrStringSequenceField):
    """A list of the module(s) you expect this test target to cover.

    Usually, Pants and pytest-cov can auto-discover this if your tests are located in the same
    folder as the `python_library` code, but this is useful if the tests are not collocated.
    """

    alias = "coverage"
    v1_only = True


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
    core_fields = (*COMMON_PYTHON_FIELDS, PythonTestsSources, PythonCoverage, PythonTestsTimeout)


# -----------------------------------------------------------------------------------------------
# `python_distribution` target
# -----------------------------------------------------------------------------------------------


class PythonDistributionSources(PythonSources):
    default = ("*.py",)

    def validate_snapshot(self, snapshot: Snapshot) -> None:
        if self.prefix_glob_with_address("setup.py") not in snapshot.files:
            raise InvalidFieldException(
                f"The {repr(self.alias)} field in target {self.address} must include "
                f"`setup.py`. All resolved files: {sorted(snapshot.files)}."
            )


class PythonDistributionSetupRequires(StringSequenceField):
    """A list of pip-style requirement strings to provide during the invocation of setup.py."""

    alias = "setup_requires"


class PythonDistribution(Target):
    """A Python distribution target that accepts a user-defined setup.py."""

    alias = "python_dist"
    core_fields = (
        *COMMON_PYTHON_FIELDS,
        PythonDistributionSources,
        PythonDistributionSetupRequires,
    )
    v1_only = True


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


# -----------------------------------------------------------------------------------------------
# `unpacked_wheels` target
# -----------------------------------------------------------------------------------------------


class UnpackedWheelsModuleName(StringField):
    """The name of the specific Python module containing headers and/or libraries to extract (e.g.
    'tensorflow')."""

    alias = "module_name"
    required = True


class UnpackedWheelsRequestedLibraries(StringSequenceField):
    """Addresses of python_requirement_library targets that specify the wheels you want to
    unpack."""

    alias = "libraries"
    required = True


class UnpackedWheelsIncludePatterns(StringSequenceField):
    """Fileset patterns to include from the archive."""

    alias = "include_patterns"


class UnpackedWheelsExcludePatterns(StringSequenceField):
    """Fileset patterns to exclude from the archive.

    Exclude patterns are processed before include_patterns.
    """

    alias = "exclude_patterns"


class UnpackedWheelsWithinDataSubdir(BoolField):
    """If True, descend into '<name>-<version>.data/' when matching `include_patterns`.

    For Python wheels which declare any non-code data, this is usually needed to extract that
    without manually specifying the relative path, including the package version.

    For example, when `data_files` is used in a setup.py, `within_data_subdir=True` will allow
    specifying `include_patterns` matching exactly what is specified in the setup.py.
    """

    alias = "within_data_subdir"
    default = False


class UnpackedWheels(Target):
    """A set of sources extracted from wheel files.

    Currently, wheels are always resolved for the 'current' platform.
    """

    alias = "unpacked_whls"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        PythonInterpreterCompatibility,
        UnpackedWheelsModuleName,
        UnpackedWheelsRequestedLibraries,
        UnpackedWheelsIncludePatterns,
        UnpackedWheelsExcludePatterns,
        UnpackedWheelsWithinDataSubdir,
    )
    v1_only = True
