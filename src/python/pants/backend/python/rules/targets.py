# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import PurePath
from typing import Any, ClassVar, Optional

from pants.build_graph.address import Address
from pants.engine.objects import union
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    BoolField,
    PrimitiveField,
    Sources,
    SourcesResult,
    StringField,
    StringOrStringListField,
    Target,
)


@union
class PythonSources(Sources):
    @classmethod
    def validate_result(cls, result: SourcesResult) -> None:
        non_python_files = [fp for fp in result.snapshot.files if not PurePath(fp).suffix == ".py"]
        if non_python_files:
            raise ValueError(
                f"Target {result.address} has non-Python sources in its `sources` field: "
                f"{non_python_files}"
            )


class PythonLibrarySources(PythonSources):
    default_globs: ClassVar = ("*.py", "!test_*.py", "!*_test.py", "!conftest.py")


class PythonTestsSources(PythonSources):
    default_globs: ClassVar = ("test_*.py", "*_test.py", "conftest.py")


class PythonBinarySources(PythonSources):
    @classmethod
    def validate_result(cls, result: SourcesResult) -> None:
        super().validate_result(result)
        if len(result.snapshot.files) not in [0, 1]:
            raise ValueError(
                "Binary targets must have only 0 or 1 source files. Any additional files should "
                "be put in a `python_library` which is added to `dependencies`"
            )


class Compatibility(StringOrStringListField):
    """A string for Python interpreter constraints on this target.

    This should be written in Requirement-style format, e.g. `CPython==2.7.*` or `CPython>=3.6,<4`.

    As a shortcut, you can leave off `CPython`, e.g. `>=2.7` will be expanded to `CPython>=2.7`.
    """

    alias: ClassVar = "compatibility"


# TODO: Deal with the `provides` field. This will at least allow us to correctly parse the valid,
#  rather than throwing an error when encountering it.
class Provides(PrimitiveField):
    alias: ClassVar = "provides"

    def hydrate(self, *, address: Address) -> Any:
        return self.raw_value


class Coverage(StringOrStringListField):
    """The module(s) whose coverage should be generated, e.g. `['pants.util']`."""

    alias: ClassVar = "coverage"


class Timeout(PrimitiveField):
    """A timeout (in seconds) which covers the total runtime of all tests in this target.

    This only applies if `--pytest-timeouts` is set to True.
    """

    alias: ClassVar = "timeout"
    raw_value: Optional[int]

    def hydrate(self, *, address: Address) -> Optional[int]:
        if self.raw_value is not None and self.raw_value <= 0:
            raise ValueError(
                f"The `{self.alias}` field for the target {address} must be > 1. Was "
                f"{self.raw_value}."
            )
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


COMMON_PYTHON_FIELDS = (*COMMON_TARGET_FIELDS, Compatibility, Provides)


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


def targets():
    return [PythonBinary, PythonLibrary, PythonTests]
