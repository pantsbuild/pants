# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
from pathlib import PurePath
from typing import Iterable, Optional, Tuple, Union, cast

from pants.backend.python.python_artifact import PythonArtifact
from pants.backend.python.subsystems.pytest import PyTest
from pants.base.deprecated import deprecated_conditional
from pants.build_graph.address import Address
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
from pants.rules.core.determine_source_files import SourceFiles
from pants.rules.core.targets import FilesSources

# -----------------------------------------------------------------------------------------------
# Common fields
# -----------------------------------------------------------------------------------------------


class PythonSources(Sources):
    # TODO: uncomment this once done with the deprecation of using non-Python files.
    # expected_file_extensions = (".py",)
    def validate_snapshot(self, snapshot: Snapshot) -> None:
        super().validate_snapshot(snapshot)
        non_python_files = [fp for fp in snapshot.files if PurePath(fp).suffix != ".py"]
        deprecated_conditional(
            lambda: bool(non_python_files),
            entity_description="Python targets including non-Python files",
            removal_version="1.29.0.dev0",
            hint_message=(
                f"The {repr(self.alias)} field in target {self.address} should only contain "
                f"files that end in '.py', but it had these files: {sorted(non_python_files)}.\n\n"
                "Instead, put those files in another target, like a `resources` target, and add "
                "that target to the `dependencies` field of this target."
            ),
        )


class PythonInterpreterCompatibility(StringOrStringSequenceField):
    """A string for Python interpreter constraints on this target.

    This should be written in Requirement-style format, e.g. `CPython==2.7.*` or `CPython>=3.6,<4`.

    As a shortcut, you can leave off `CPython`, e.g. `>=2.7` will be expanded to `CPython>=2.7`.
    """

    alias = "compatibility"

    def value_or_global_default(self, python_setup: PythonSetup) -> Tuple[str, ...]:
        """Return either the given `compatibility` field or the global interpreter constraints.

        If interpreter constraints are supplied by the CLI flag, return those only.
        """
        return python_setup.compatibility_or_constraints(self.value)


class PythonProvidesField(ScalarField, ProvidesField):
    """The`setup.py` kwargs for the external artifact built from this target."""

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
    expected_num_files = range(0, 2)


class PythonEntryPoint(StringField):
    """The default entry point for the binary.

    If omitted, Pants will try to infer the entry point by looking at the `source` argument for a
    `__main__` function.
    """

    alias = "entry_point"


class PythonPlatforms(StringOrStringSequenceField):
    """Extra platforms to target when building a Python binary.

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


class PexAlwaysWriteCache(BoolField):
    """Whether Pex should always write the .deps cache of the Pex file to disk or not.

    This can use less memory in RAM constrained environments.
    """

    alias = "always_write_cache"
    default = False


class PexIgnoreErrors(BoolField):
    """Should we ignore when Pex cannot resolve dependencies?"""

    alias = "ignore_errors"
    default = False


class PexShebang(StringField):
    """For the generated Pex, use this shebang."""

    alias = "shebang"


# TODO: This option is weird. Its default is determined by `--python-binary-pex-emit-warnings`.
#  How would that work with the Target API? Likely, make this an AsyncField and in the rule
#  request the corresponding subsystem. For now, we ignore the option.
class PexEmitWarnings(BoolField):
    """Whether or not to emit Pex warnings at runtime."""

    alias = "emit_warnings"
    default = True


class PythonBinary(Target):
    """A Python target that can be converted into an executable Pex file.

    Pex files are self-contained executable files that contain a complete Python
    environment capable of running the target. For more information about Pex files, see
    http://pantsbuild.github.io/python-readme.html#how-pex-files-work.
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
    """The module(s) whose coverage should be generated, e.g. `['pants.util']`."""

    alias = "coverage"

    def determine_packages_to_cover(
        self, *, specified_source_files: SourceFiles
    ) -> Tuple[str, ...]:
        """Either return the specified `coverage` field value or, if not defined, attempt to
        generate packages with a heuristic that tests have the same package name as their source
        code.

        This heuristic about package names works when either the tests live in the same folder as
        their source code, or there is a parallel file structure with the same top-level package
        names, e.g. `src/python/project` and `tests/python/project` (but not
        `tests/python/test_project`).
        """
        if self.value is not None:
            return self.value
        return tuple(
            sorted(
                {
                    # Turn file paths into package names.
                    os.path.dirname(source_file).replace(os.sep, ".")
                    for source_file in specified_source_files.snapshot.files
                }
            )
        )


class PythonTestsTimeout(IntField):
    """A timeout (in seconds) which covers the total runtime of all tests in this target.

    This only applies if `--pytest-timeouts` is set to True.
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
    """Python tests (either Pytest-style or unittest style)."""

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
    """A sequence of `python_requirement` objects."""

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
    """A set of Pip requirements."""

    alias = "python_requirement_library"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, PythonRequirementsField)


# -----------------------------------------------------------------------------------------------
# `_python_requirements_file` target
# -----------------------------------------------------------------------------------------------


# NB: This subclasses FilesSources to ensure that we still properly handle stripping source roots,
# but we still new type so that we can distinguish between normal FilesSources vs. this field.
class PythonRequirementsFileSources(FilesSources):
    pass


# TODO: filter out private targets from `./pants target-types2`? Simply check for `_`. This
#  probably depends on how common this private target pattern will end being, which is unclear now
#  that we have Configurations for ad hoc, internal combinations of fields.
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

    @classmethod
    def compute_value(  # type: ignore[override]
        cls, raw_value: Optional[Union[bool, str]], *, address: Address
    ) -> Union[bool, str]:
        if isinstance(raw_value, str):
            return raw_value
        return super().compute_value(raw_value, address=address)


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
