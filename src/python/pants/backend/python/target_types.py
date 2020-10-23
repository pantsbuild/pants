# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import collections.abc
import logging
import os.path
from dataclasses import dataclass
from textwrap import dedent
from typing import Iterable, Optional, Tuple, Union, cast

from pkg_resources import Requirement

from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.subsystems.pytest import PyTest
from pants.base.deprecated import resolve_conflicting_options, warn_or_error
from pants.core.goals.package import OutputPathField
from pants.engine.addresses import Address, Addresses, UnparsedAddressInputs
from pants.engine.fs import PathGlobs, Paths
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    BoolField,
    Dependencies,
    DictStringToStringSequenceField,
    InjectDependenciesRequest,
    InjectedDependencies,
    IntField,
    InvalidFieldException,
    InvalidFieldTypeException,
    PrimitiveField,
    ProvidesField,
    ScalarField,
    Sources,
    SpecialCasedDependencies,
    StringField,
    StringOrStringSequenceField,
    StringSequenceField,
    Target,
    WrappedTarget,
)
from pants.option.global_options import FilesNotFoundBehavior
from pants.option.subsystem import Subsystem
from pants.python.python_requirement import PythonRequirement
from pants.python.python_setup import PythonSetup
from pants.source.source_root import SourceRoot, SourceRootRequest

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------------------------
# Common fields
# -----------------------------------------------------------------------------------------------


class PythonSources(Sources):
    expected_file_extensions = (".py", ".pyi")


class PythonInterpreterCompatibility(StringOrStringSequenceField):
    """A string for Python interpreter constraints on this target.

    This should be written in Requirement-style format, e.g. `CPython==2.7.*` or `CPython>=3.6,<4`.
    As a shortcut, you can leave off `CPython`, e.g. `>=2.7` will be expanded to `CPython>=2.7`.

    If this is left off, this will default to the option `interpreter_constraints` in the
    [python-setup] scope.

    See https://www.pantsbuild.org/docs/python-interpreter-compatibility.
    """

    alias = "compatibility"

    def value_or_global_default(self, python_setup: PythonSetup) -> Tuple[str, ...]:
        """Return either the given `compatibility` field or the global interpreter constraints.

        If interpreter constraints are supplied by the CLI flag, return those only.
        """
        return python_setup.compatibility_or_constraints(self.value)


COMMON_PYTHON_FIELDS = (*COMMON_TARGET_FIELDS, PythonInterpreterCompatibility)


# -----------------------------------------------------------------------------------------------
# `pex_binary` target
# -----------------------------------------------------------------------------------------------


class PexBinaryDefaults(Subsystem):
    """Default settings for creating PEX executables."""

    options_scope = "pex-binary-defaults"
    deprecated_options_scope = "python-binary"
    deprecated_options_scope_removal_version = "2.1.0.dev0"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--pex-emit-warnings",
            advanced=True,
            type=bool,
            default=True,
            help=(
                "Whether built PEX binaries should emit pex warnings at runtime by default. "
                "Can be overridden by specifying the `emit_warnings` parameter of individual "
                "`pex_binary` targets"
            ),
            removal_version="2.1.0.dev0",
            removal_hint="Use `emit_warnings` rather than `pex_emit_warnings`.",
        )
        register(
            "--emit-warnings",
            advanced=True,
            type=bool,
            default=True,
            help=(
                "Whether built PEX binaries should emit PEX warnings at runtime by default. "
                "Can be overridden by specifying the `emit_warnings` parameter of individual "
                "`pex_binary` targets"
            ),
        )

    @property
    def emit_warnings(self) -> bool:
        return cast(
            bool,
            resolve_conflicting_options(
                old_option="pex_emit_warnings",
                new_option="emit_warnings",
                old_scope=self.options_scope,
                new_scope=self.deprecated_options_scope,
                old_container=self.options,
                new_container=self.options,
            ),
        )


class PexBinarySources(PythonSources):
    """A single file containing the executable, such as ['app.py'].

    You can leave this off if you include the executable file in one of this target's
    `dependencies` and explicitly set this target's `entry_point`.

    This must have 0 or 1 files, but no more. If you depend on more files, put them in a
    `python_library` target and include that target in the `dependencies` field.
    """

    expected_num_files = range(0, 2)


class PexBinaryDependencies(Dependencies):
    supports_transitive_excludes = True


class PexEntryPointField(StringField):
    """The entry point for the binary.

    If omitted, Pants will use the module name from the `sources` field, e.g. `project/app.py` will
    become the entry point `project.app` .
    """

    alias = "entry_point"


@dataclass(frozen=True)
class ResolvedPexEntryPoint:
    val: str


@dataclass(frozen=True)
class ResolvePexEntryPointRequest:
    """Determine the entry_point by using the `PexEntryPointField` and falling back to the sources
    field."""

    entry_point_field: PexEntryPointField
    sources: PexBinarySources


@rule
async def resolve_pex_entry_point(request: ResolvePexEntryPointRequest) -> ResolvedPexEntryPoint:
    if request.entry_point_field.value:
        return ResolvedPexEntryPoint(request.entry_point_field.value)
    binary_source_paths = await Get(
        Paths, PathGlobs, request.sources.path_globs(FilesNotFoundBehavior.error)
    )
    if len(binary_source_paths.files) != 1:
        raise InvalidFieldException(
            "No `entry_point` was set for the target "
            f"{repr(request.sources.address)}, so it must have exactly one source, but it has "
            f"{len(binary_source_paths.files)}."
        )
    entry_point_path = binary_source_paths.files[0]
    source_root = await Get(
        SourceRoot,
        SourceRootRequest,
        SourceRootRequest.for_file(entry_point_path),
    )
    stripped_source_path = os.path.relpath(entry_point_path, source_root.path)
    module_base, _ = os.path.splitext(stripped_source_path)
    return ResolvedPexEntryPoint(module_base.replace(os.path.sep, "."))


class PexPlatformsField(StringOrStringSequenceField):
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


class PexInheritPathField(StringField):
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


class PexZipSafeField(BoolField):
    """Whether or not this binary is safe to run in compacted (zip-file) form.

    If the PEX is not zip safe, it will be written to disk prior to execution. You may need to mark
    `zip_safe=False` if you're having issues loading your code.
    """

    alias = "zip_safe"
    default = True
    value: bool


class PexAlwaysWriteCacheField(BoolField):
    """Whether PEX should always write the .deps cache of the .pex file to disk or not.

    This can use less memory in RAM constrained environments.
    """

    alias = "always_write_cache"
    default = False
    value: bool


class PexIgnoreErrorsField(BoolField):
    """Should we ignore when PEX cannot resolve dependencies?"""

    alias = "ignore_errors"
    default = False
    value: bool


class PexShebangField(StringField):
    """Set the generated PEX to use this shebang, rather than the default of PEX choosing a shebang
    based on the interpreter constraints.

    This influences the behavior of running `./result.pex`. You can ignore the shebang by instead
    running `/path/to/python_interpreter ./result.pex`.
    """

    alias = "shebang"


class PexEmitWarningsField(BoolField):
    """Whether or not to emit PEX warnings at runtime.

    The default is determined by the option `emit_warnings` in the `[pex-binary-defaults]` scope.
    """

    alias = "emit_warnings"

    def value_or_global_default(self, pex_binary_defaults: PexBinaryDefaults) -> bool:
        if self.value is None:
            return pex_binary_defaults.emit_warnings
        return self.value


class PexBinary(Target):
    """A Python target that can be converted into an executable PEX file.

    PEX files are self-contained executable files that contain a complete Python environment capable
    of running the target. For more information, see https://www.pantsbuild.org/docs/pex-files.
    """

    alias = "pex_binary"
    core_fields = (
        *COMMON_PYTHON_FIELDS,
        OutputPathField,
        PexBinarySources,
        PexBinaryDependencies,
        PexEntryPointField,
        PexPlatformsField,
        PexInheritPathField,
        PexZipSafeField,
        PexAlwaysWriteCacheField,
        PexIgnoreErrorsField,
        PexShebangField,
        PexEmitWarningsField,
    )


class PythonBinary(PexBinary):
    """A Python target that can be converted into an executable PEX file.

    PEX files are self-contained executable files that contain a complete Python environment capable
    of running the target. For more information, see https://www.pantsbuild.org/docs/pex-files.
    """

    alias = "python_binary"
    deprecated_removal_version = "2.1.0.dev0"
    deprecated_removal_hint = (
        "Use `pex_binary` instead, which behaves identically.\n\nTo fix this globally, run the "
        "below command:\n\tmacOS: for f in $(find . -name BUILD); do sed -i '' -Ee "
        "'s#^python_binary\\(#pex_binary(#g' $f ; done\n\tLinux: for f in $(find . -name BUILD); "
        "do sed -i -Ee 's#^python_binary\\(#pex_binary(#g' $f ; done"
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


class PythonRuntimePackageDependencies(SpecialCasedDependencies):
    """Addresses to targets that can be built with the `./pants package` goal and whose resulting
    assets should be included in the test run.

    Pants will build the assets as if you had run `./pants package`. It will include the
    results in your archive using the same name they would normally have, but without the
    `--distdir` prefix (e.g. `dist/`).

    You can include anything that can be built by `./pants package`, e.g. a `pex_binary`,
    `python_awslambda`, or an `archive`.
    """

    alias = "runtime_package_dependencies"


class PythonRuntimeBinaryDependencies(SpecialCasedDependencies):
    """Deprecated in favor of the `runtime_build_dependencies` field, which works with more target
    types like `archive` and `python_awslambda`."""

    alias = "runtime_binary_dependencies"
    deprecated_removal_version = "2.1.0dev0"
    deprecated_removal_hint = "Use the more flexible `runtime_package_dependencies` field instead."


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


class DeprecatedCoverageField(StringOrStringSequenceField):
    alias = "coverage"
    deprecated_removal_version = "2.1.0.dev0"
    deprecated_removal_hint = (
        "The `coverage` field no longer does anything, as Pants now gets coverage data for all "
        "files encountered. Use the option `--coverage-py-filter` if you want more precise "
        "results. See https://www.pantsbuild.org/docs/python-test-goal#coverage."
    )


class PythonTests(Target):
    """Python tests.

    These may be written in either Pytest-style or unittest style.

    All test util code, other than `conftest.py`, should go into a dedicated `python_library()`
    target and then be included in the `dependencies` field.

    See https://www.pantsbuild.org/docs/python-test-goal.
    """

    alias = "python_tests"
    core_fields = (
        *COMMON_PYTHON_FIELDS,
        PythonTestsSources,
        PythonTestsDependencies,
        PythonRuntimePackageDependencies,
        PythonRuntimeBinaryDependencies,
        PythonTestsTimeout,
        DeprecatedCoverageField,
    )


# -----------------------------------------------------------------------------------------------
# `python_library` target
# -----------------------------------------------------------------------------------------------


class PythonLibrarySources(PythonSources):
    default = ("*.py", "*.pyi") + tuple(f"!{pat}" for pat in PythonTestsSources.default)


class DeprecatedProvidesField(ScalarField, ProvidesField):
    expected_type = PythonArtifact
    expected_type_description = "setup_py(name='my-dist', **kwargs)"
    value: PythonArtifact
    deprecated_removal_version = "2.1.0.dev0"
    deprecated_removal_hint = (
        "Rather than using the `provides` field on a `python_library` target, create a dedicated "
        "`python_distribution` target. See "
        "https://www.pantsbuild.org/docs/how-to-upgrade-pants-2-0#use--python_distribution-"
        "target-type-for-providessetup_py-130-vs-20 for instructions."
    )

    @classmethod
    def compute_value(
        cls, raw_value: Optional[PythonArtifact], *, address: Address
    ) -> PythonArtifact:
        return cast(PythonArtifact, super().compute_value(raw_value, address=address))


class PythonLibrary(Target):
    """Python source code.

    A `python_library` does not necessarily correspond to a distribution you publish (see
    `python_distribution` and `pex_binary` for that); multiple `python_library` targets may be
    packaged into a distribution or binary.
    """

    alias = "python_library"
    core_fields = (
        *COMMON_PYTHON_FIELDS,
        Dependencies,
        PythonLibrarySources,
        DeprecatedProvidesField,
    )


# -----------------------------------------------------------------------------------------------
# `python_requirement_library` target
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


class PythonRequirementsField(PrimitiveField):
    """A sequence of pip-style requirement strings, e.g. ['foo==1.8', 'bar<=3 ;
    python_version<'3']."""

    alias = "requirements"
    required = True
    value: Tuple[Requirement, ...]

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Iterable[str]], *, address: Address
    ) -> Tuple[Requirement, ...]:
        value = super().compute_value(raw_value, address=address)
        invalid_type_error = InvalidFieldTypeException(
            address,
            cls.alias,
            value,
            expected_type="an iterable of pip-style requirement strings (e.g. a list)",
        )
        if isinstance(value, (str, PythonRequirement)) or not isinstance(
            value, collections.abc.Iterable
        ):
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
            elif isinstance(v, PythonRequirement):
                extra_suggestions = ""
                if v.repository:
                    extra_suggestions += (
                        f"\n\nInstead of setting 'repository={v.repository}`, add this to the "
                        "option `repos` in the `[python-repos]` options scope."
                    )
                warn_or_error(
                    removal_version="2.1.0.dev0",
                    deprecated_entity_description="Using `pants_requirement`",
                    hint=(
                        f"In the '{cls.alias}' field for {address}, use '{str(v.requirement)}' "
                        f"instead of 'pants_requirement('{str(v.requirement)}').{extra_suggestions}"
                    ),
                )
                result.append(v.requirement)
            else:
                raise invalid_type_error
        return tuple(result)


class ModuleMappingField(DictStringToStringSequenceField):
    """A mapping of requirement names to a list of the modules they provide.

    For example, `{"ansicolors": ["colors"]}`. Any unspecified requirements will use the
    requirement name as the default module, e.g. "Django" will default to ["django"]`.

    This is used for Pants to be able to infer dependencies in BUILD files.
    """

    alias = "module_mapping"


class PythonRequirementLibrary(Target):
    """Python requirements installable by pip.

    This target is useful when you want to declare Python requirements inline in a BUILD file. If
    you have a `requirements.txt` file already, you can instead use the macro
    `python_requirements()` to convert each requirement into a `python_requirement_library()` target
    automatically.

    See https://www.pantsbuild.org/docs/python-third-party-dependencies.
    """

    alias = "python_requirement_library"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, PythonRequirementsField, ModuleMappingField)


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
# `python_distribution` target
# -----------------------------------------------------------------------------------------------


class PythonDistributionDependencies(Dependencies):
    supports_transitive_excludes = True


class PythonProvidesField(ScalarField, ProvidesField):
    """The setup.py kwargs for the external artifact built from this target.

    See https://www.pantsbuild.org/docs/python-setup-py-goal.
    """

    expected_type = PythonArtifact
    expected_type_description = "setup_py(name='my-dist', **kwargs)"
    value: PythonArtifact
    required = True

    @classmethod
    def compute_value(
        cls, raw_value: Optional[PythonArtifact], *, address: Address
    ) -> PythonArtifact:
        return cast(PythonArtifact, super().compute_value(raw_value, address=address))


class SetupPyCommandsField(StringSequenceField):
    """The runtime commands to invoke setup.py with to create the distribution.

    E.g., ["bdist_wheel", "--python-tag=py36.py37", "sdist"]

    If empty or unspecified, will just create a chroot with a setup() function.

    See https://www.pantsbuild.org/docs/python-setup-py-goal.
    """

    alias = "setup_py_commands"
    expected_type_description = (
        "an iterable of string commands to invoke setup.py with, or "
        "an empty list to just create a chroot with a setup() function."
    )


class PythonDistribution(Target):
    """A publishable Python setuptools distribution (e.g. an sdist or wheel)."""

    alias = "python_distribution"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        PythonDistributionDependencies,
        PythonProvidesField,
        SetupPyCommandsField,
    )


class InjectPythonDistributionDependencies(InjectDependenciesRequest):
    inject_for = PythonDistributionDependencies


@rule
async def inject_dependencies(
    request: InjectPythonDistributionDependencies,
) -> InjectedDependencies:
    """Inject any `.with_binaries()` values, as it would be redundant to have to include in the
    `dependencies` field."""
    original_tgt = await Get(WrappedTarget, Address, request.dependencies_field.address)
    with_binaries = original_tgt.target[PythonProvidesField].value.binaries
    if not with_binaries:
        return InjectedDependencies()
    # Note that we don't validate that these are all `pex_binary` targets; we don't care about
    # that here. `setup_py.py` will do that validation.
    addresses = await Get(
        Addresses,
        UnparsedAddressInputs(
            with_binaries.values(), owning_address=request.dependencies_field.address
        ),
    )
    return InjectedDependencies(addresses)


def rules():
    return collect_rules()
