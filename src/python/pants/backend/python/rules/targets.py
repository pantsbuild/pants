# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import PurePath
from typing import Optional

from pants.build_graph.address import Address
from pants.engine.fs import Snapshot
from pants.engine.objects import union
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    BoolField,
    IntField,
    InvalidFieldException,
    Sources,
    StringField,
    StringOrStringSequenceField,
    Target,
    UnimplementedField,
)


@union
class PythonSources(Sources):
    def validate_snapshot(self, snapshot: Snapshot) -> None:
        non_python_files = [fp for fp in snapshot.files if not PurePath(fp).suffix == ".py"]
        if non_python_files:
            raise InvalidFieldException(
                f"The {repr(self.alias)} field in target {self.address} must only contain Python "
                f"files that end in `.py`, but it had these non-Python files: {non_python_files}."
            )


class PythonLibrarySources(PythonSources):
    default_globs = ("*.py", "!test_*.py", "!*_test.py", "!conftest.py")


class PythonTestsSources(PythonSources):
    default_globs = ("test_*.py", "*_test.py", "conftest.py")


class PythonBinarySources(PythonSources):
    def validate_snapshot(self, snapshot: Snapshot) -> None:
        super().validate_snapshot(snapshot)
        if len(snapshot.files) not in [0, 1]:
            raise InvalidFieldException(
                f"The {repr(self.alias)} field in target {self.address} must only have 0 or 1 "
                f"files because it is a binary target, but it has {len(snapshot.files)} sources: "
                f"{sorted(snapshot.files)}.\n\nTo use any additional files, put them in a "
                "`python_library` and then add that `python_library` as a `dependency`."
            )


class Compatibility(StringOrStringSequenceField):
    """A string for Python interpreter constraints on this target.

    This should be written in Requirement-style format, e.g. `CPython==2.7.*` or `CPython>=3.6,<4`.

    As a shortcut, you can leave off `CPython`, e.g. `>=2.7` will be expanded to `CPython>=2.7`.
    """

    alias = "compatibility"


class Provides(UnimplementedField):
    alias = "provides"


class Coverage(StringOrStringSequenceField):
    """The module(s) whose coverage should be generated, e.g. `['pants.util']`."""

    alias = "coverage"


class Timeout(IntField):
    """A timeout (in seconds) which covers the total runtime of all tests in this target.

    This only applies if `--pytest-timeouts` is set to True.
    """

    alias = "timeout"

    def hydrate(self, raw_value: Optional[int], *, address: Address) -> Optional[int]:
        hydrated_value = super().hydrate(raw_value, address=address)
        if hydrated_value is not None and hydrated_value < 1:
            raise InvalidFieldException(
                f"The value for the `timeout` field in target {address} must be >= 1, but was "
                f"{raw_value}."
            )
        return raw_value


class EntryPoint(StringField):
    """The default entry point for the binary.

    If omitted, Pants will try to infer the entry point by looking at the `source` argument for a
    `__main__` function.
    """

    alias = "entry_point"


class Platforms(StringOrStringSequenceField):
    """Extra platforms to target when building a Python binary."""

    alias = "platforms"


class PexInheritPath(BoolField):
    """Whether to inherit the `sys.path` of the environment that the binary runs in or not."""

    alias = "inherit_path"
    default = False


class PexZipSafe(BoolField):
    """Whether or not this binary is safe to run in compacted (zip-file) form."""

    alias = "zip_safe"
    default = True


class PexAlwaysWriteCache(BoolField):
    """Whether Pex should always write the .deps cache of the Pex file to disk or not."""

    alias = "always_write_cache"
    default = False


class PexRepositories(StringOrStringSequenceField):
    """Repositories for Pex to query for dependencies."""

    alias = "repositories"


class PexIndices(StringOrStringSequenceField):
    """Indices for Pex to use for packages."""

    alias = "indices"


class IgnorePexErrors(BoolField):
    """Should we ignore when Pex cannot resolve dependencies?"""

    alias = "ignore_errors"
    default = False


class PexShebang(StringField):
    """For the generated Pex, use this shebang."""

    alias = "shebang"


# TODO: This option is weird. Its default is determined by `--python-binary-pex-emit-warnings`.
#  How would that work with the Target API? Likely, make this an AsyncField and in the rule
#  request the corresponding subsystem. For now, we ignore the option.
class EmitPexWarnings(BoolField):
    """Whether or not to emit Pex warnings at runtime."""

    alias = "emit_warnings"
    default = True


COMMON_PYTHON_FIELDS = (*COMMON_TARGET_FIELDS, Compatibility, Provides)


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
    alias = "python_library"
    core_fields = (*COMMON_PYTHON_FIELDS, PythonLibrarySources)


class PythonTests(Target):
    alias = "python_tests"
    core_fields = (*COMMON_PYTHON_FIELDS, PythonTestsSources, Coverage, Timeout)
