# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import PurePath
from typing import ClassVar, Optional

from pants.engine.rules import rule
from pants.engine.selectors import Get
from pants.engine.target import (
    BoolField,
    HydrateSourcesRequest,
    PrimitiveField,
    Sources,
    SourcesResult,
    StringField,
    StringOrStringListField,
    Target,
)
from pants.util.memo import memoized_property

# TODO: Deal with the `provides` field.


class PythonSources(Sources):
    @staticmethod
    def validate_result(result: SourcesResult) -> None:
        non_python_files = [fp for fp in result.snapshot.files if not PurePath(fp).suffix == ".py"]
        if non_python_files:
            raise ValueError("")


class PythonLibrarySources(PythonSources):
    default_globs: ClassVar = ("*.py", "!test_*.py", "!*_test.py", "!conftest.py")


class PythonTestsSources(PythonSources):
    default_globs: ClassVar = ("test_*.py", "*_test.py", "conftest.py")


class PythonBinarySources(PythonSources):
    @staticmethod
    def validate_result(result: SourcesResult) -> None:
        super().validate_result(result)
        if len(result.snapshot.files) not in [0, 1]:
            raise ValueError(
                "Binary targets must have only 0 or 1 source files. Any additional files should "
                "be put in a `python_library` which is added to `dependencies`"
            )


# TODO: should these be union rules..? I think the call sites here are nice, to be able to say
# `await Get[SourcesResult](Sources, my_tgt.get(Sources)`
@rule
async def hydrate_python_sources(sources: PythonSources) -> SourcesResult:
    return await Get[SourcesResult](HydrateSourcesRequest(sources))


@rule
async def hydrate_python_library_sources(sources: PythonLibrarySources) -> SourcesResult:
    return await Get[SourcesResult](HydrateSourcesRequest(sources))


@rule
async def hydrate_python_tests_sources(sources: PythonTestsSources) -> SourcesResult:
    return await Get[SourcesResult](HydrateSourcesRequest(sources))


@rule
async def hydrate_python_binary_sources(sources: PythonBinarySources) -> SourcesResult:
    return await Get[SourcesResult](HydrateSourcesRequest(sources))


class Compatibility(StringOrStringListField):
    """A string for Python interpreter constraints on this target.

    This should be written in Requirement-style format, e.g. `CPython==2.7.*` or `CPython>=3.6,<4`.

    As a shortcut, you can leave off `CPython`, e.g. `>=2.7` will be expanded to `CPython>=2.7`.
    """

    alias: ClassVar = "compatibility"


class Coverage(StringOrStringListField):
    """The module(s) whose coverage should be generated, e.g. `['pants.util']`."""

    alias: ClassVar = "coverage"


class Timeout(PrimitiveField):
    """A timeout (in seconds) which covers the total the total runtime of all tests in this target.

    This only applies if `--pytest-timeouts` is set to True.
    """

    alias: ClassVar = "timeout"
    raw_value: Optional[int]

    @memoized_property
    def value(self) -> Optional[int]:
        if self.raw_value is None:
            return None
        if not isinstance(self.raw_value, int):
            raise ValueError(
                f"The `timeout` field must be an `int`. Was {type(self.raw_value)} "
                f"({self.raw_value})."
            )
        if self.raw_value <= 0:
            raise ValueError(f"The `timeout` field must be > 1. Was {self.raw_value}.")
        return self.raw_value


class EntryPoint(StringField):
    """The default entry point for the binary.

    If omitted, Pants will try to infer the entry point by looking at the `source` argument for a
    `__main__` function.
    """

    alias: ClassVar = "entry_point"


class Platforms(StringOrStringListField):
    """Extra platforms to target when building a Python binary."""

    alias: ClassVar = "platforms"


class PexInheritPath(BoolField):
    """Whether to inherit the `sys.path` of the environment that the binary runs in or not."""

    alias: ClassVar = "inherit_path"
    default: ClassVar = False


class PexZipSafe(BoolField):
    """Whether or not this binary is safe to run in compacted (zip-file) form."""

    alias: ClassVar = "zip_safe"
    default: ClassVar = True


class PexAlwaysWriteCache(BoolField):
    """Whether Pex should always write the .deps cache of the Pex file to disk or not."""

    alias: ClassVar = "always_write_cache"
    default: ClassVar = False


class PexRepositories(StringOrStringListField):
    """Repositories for Pex to query for dependencies."""

    alias: ClassVar = "repositories"


class PexIndices(StringOrStringListField):
    """Indices for Pex to use for packages."""

    alias: ClassVar = "indices"


class IgnorePexErrors(BoolField):
    """Should we ignore when Pex cannot resolve dependencies?"""

    alias: ClassVar = "ignore_errors"
    default: ClassVar = False


class PexShebang(StringField):
    """For the generated Pex, use this shebang."""

    alias: ClassVar = "shebang"


# TODO: This option is weird. Its default is determined by `--python-binary-pex-emit-warnings`.
#  How would that work with the Target API? Likely, make this an AsyncField and in the rule
#  request the corresponding subsystem. For now, we ignore the option.
class EmitPexWarnings(BoolField):
    """Whether or not to emit Pex warnings at runtime."""

    alias: ClassVar = "emit_warnings"
    default: ClassVar = True


COMMON_PYTHON_FIELDS = (Compatibility,)


class PythonBinary(Target):
    """A Python target that can be converted into an executable Pex file.

    Pex files are self-contained executable files that contain a complete Python
    environment capable of running the target. For more information about Pex files, see
    http://pantsbuild.github.io/python-readme.html#how-pex-files-work.
    """

    alias: ClassVar = "python_binary"
    core_fields: ClassVar = (
        *COMMON_PYTHON_FIELDS,
        PythonBinarySources,
        EntryPoint,
        Platforms,
        PexInheritPath,
        PexZipSafe,
        PexAlwaysWriteCache,
        PexRepositories,
        PexIndices,
        IgnorePexErrors,
        PexShebang,
        EmitPexWarnings,
    )


class PythonLibrary(Target):
    alias: ClassVar = "python_library"
    core_fields: ClassVar = (*COMMON_PYTHON_FIELDS, PythonLibrarySources)


class PythonTests(Target):
    alias: ClassVar = "python_tests"
    core_fields: ClassVar = (*COMMON_PYTHON_FIELDS, PythonTestsSources, Coverage, Timeout)


def rules():
    return [
        hydrate_python_sources,
        hydrate_python_binary_sources,
        hydrate_python_library_sources,
        hydrate_python_tests_sources,
    ]


def targets():
    return [PythonBinary, PythonLibrary, PythonTests]
