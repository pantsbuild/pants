# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Tuple, Type, TypeVar

from pants.backend.python.target_types import (
    PexAlwaysWriteCache,
    PexEmitWarnings,
    PexIgnoreErrors,
    PexInheritPath,
    PexShebang,
    PexZipSafe,
    PythonBinaryDefaults,
    PythonBinarySources,
    PythonEntryPoint,
)
from pants.backend.python.target_types import PythonPlatforms as PythonPlatformsField
from pants.backend.python.util_rules.pex import PexPlatforms, TwoStepPex
from pants.backend.python.util_rules.pex_from_targets import (
    PexFromTargetsRequest,
    TwoStepPexFromTargetsRequest,
)
from pants.build_graph.address import Address
from pants.core.goals.binary import BinaryFieldSet, CreatedBinary
from pants.core.goals.run import RunFieldSet
from pants.engine.fs import PathGlobs, Paths
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import InvalidFieldException
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.option.global_options import FilesNotFoundBehavior, GlobalOptions
from pants.source.source_root import SourceRoot, SourceRootRequest
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PythonBinaryFieldSet(BinaryFieldSet, RunFieldSet):
    required_fields = (PythonEntryPoint, PythonBinarySources)

    sources: PythonBinarySources
    entry_point: PythonEntryPoint

    always_write_cache: PexAlwaysWriteCache
    emit_warnings: PexEmitWarnings
    ignore_errors: PexIgnoreErrors
    inherit_path: PexInheritPath
    shebang: PexShebang
    zip_safe: PexZipSafe
    platforms: PythonPlatformsField

    def generate_additional_args(
        self, python_binary_defaults: PythonBinaryDefaults
    ) -> Tuple[str, ...]:
        args = []
        if self.always_write_cache.value is True:
            args.append("--always-write-cache")
        if self.emit_warnings.value_or_global_default(python_binary_defaults) is False:
            args.append("--no-emit-warnings")
        if self.ignore_errors.value is True:
            args.append("--ignore-errors")
        if self.inherit_path.value is not None:
            args.append(f"--inherit-path={self.inherit_path.value}")
        if self.shebang.value is not None:
            args.append(f"--python-shebang={self.shebang.value}")
        if self.zip_safe.value is False:
            args.append("--not-zip-safe")
        return tuple(args)


# TODO: this indirection is necessary because we otherwise need to use PythonBinaryFieldSet both as
# the implementor of a UnionRule, as well as a "normal" Param to `calculate_entry_point()` below.
# This results in the error:
# E           Engine traceback:
# E             in select
# E             in pants.backend.python.goals.create_python_binary.create_python_binary (src/python/foo/bar:hello_world_lambda)
# E             in pants.backend.awslambda.python.awslambda_python_rules.create_python_awslambda
# E           Traceback (no traceback):
# E             <pants native internals>
# E           Exception: Type PythonBinaryFieldSet is not a member of the BinaryFieldSet @union ("The fields necessary to create a binary from a target.")
@dataclass(frozen=True)
class ReducedPythonBinaryFieldSet:
    address: Address
    sources: PythonBinarySources
    entry_point: PythonEntryPoint

    @classmethod
    def from_real_field_set(cls, real: PythonBinaryFieldSet) -> 'ReducedPythonBinaryFieldSet':
        return cls(real.address, real.sources, real.entry_point)


@dataclass(frozen=True)
class PythonEntryPointWrapper:
    """Alias for PythonEntryPoint without requiring an Address to construct."""
    value: str


class AlternateImplementationAck(Enum):
    """Whether an alternate implementation of python_binary() creation should be used."""
    not_applicable = 'N/A'
    can_be_used = 'usable!'


_T = TypeVar('_T', bound='PythonBinaryImplementation')


@union
class PythonBinaryImplementation(metaclass=ABCMeta):
    """@union base for plugins that wish to modify the output of `./pants binary` for python."""

    @classmethod
    @abstractmethod
    def create(cls: Type[_T], field_set: PythonBinaryFieldSet) -> _T:
        ...


@rule
async def calculate_entry_point(field_set: ReducedPythonBinaryFieldSet) -> PythonEntryPointWrapper:
    entry_point = field_set.entry_point.value
    if entry_point is None:
        binary_source_paths = await Get(
            Paths, PathGlobs, field_set.sources.path_globs(FilesNotFoundBehavior.error)
        )
        if len(binary_source_paths.files) != 1:
            raise InvalidFieldException(
                "No `entry_point` was set for the target "
                f"{repr(field_set.address)}, so it must have exactly one source, but it has "
                f"{len(binary_source_paths.files)}"
            )
        entry_point_path = binary_source_paths.files[0]
        source_root = await Get(
            SourceRoot,
            SourceRootRequest,
            SourceRootRequest.for_file(entry_point_path),
        )
        entry_point = PythonBinarySources.translate_source_file_to_entry_point(
            os.path.relpath(entry_point_path, source_root.path)
        )
    return PythonEntryPointWrapper(entry_point)


@rule(level=LogLevel.DEBUG)
async def create_python_binary(
    field_set: PythonBinaryFieldSet,
    python_binary_defaults: PythonBinaryDefaults,
    global_options: GlobalOptions,
    union_membership: UnionMembership,
) -> CreatedBinary:
    # This is an example of a method to allow plugins to change the output produced when running
    # `./pants binary` on python_binary() targets. This method of selection is intended for cases
    # where all of the relevant target-specific information already exists in PythonBinaryFieldSet.
    # This allows for plugin authors to roll out new or experimental packaging formats without
    # having to perform mass edits across the repo.
    #
    # The mechanism for determining which output to select uses UnionRule registration.
    # 1. The ordered set of @union members is linearly scanned, and each will be consulted on
    #    whether it should be used instead.
    # 2. If any of the @union members accepts, they then have the responsibility to produce their
    #    own CreatedBinary, given a PythonBinaryFieldSet, which is returned instead of executing the
    #    rest of this method.
    # For example, if `pants.backend.awslambda.python` is enabled, providing the option
    # --awslambda-python-runtime=python3.6 will produce a lambdex from the target definition.
    # The python_binary()'s `entry_point` (which may be implicit) is used as the lambdex `handler`.
    #
    # This method will ensure `./pants help binary` lists e.g. `awslambda` under related subsystems,
    # if its option values are used to select an alternative implementation, or to implement that
    # alternative.
    #
    # This method *should* be used to expose tools which pre- or post-process a PEX file, to reduce
    # BUILD file churn in cases where it is *unlikely* users will ever want to produce such a
    # processed PEX in the same command line as a normal PEX.
    # This method should *not* be used to overload python_binary() targets in cases where they do
    # not have sufficient metadata for the intended task. For example, a python_distribution()
    # target contains metadata such as `name` which cannot be safely made implicit or generated.
    #
    # The guiding principles for maintainable plugin design should be:
    # - to associate *targets* with "what the code *is*" (each source file has a *single* meaning),
    # - to associate *goals* with "what to *do* with the code" (multiple goals make sense *at once*),
    # - to associate *options* with "*how* or *how much* to do it" (to choose *one way out of many*).
    for alt_impl in union_membership.get(PythonBinaryImplementation):
        alternate_impl_request = alt_impl.create(field_set)
        alternate_implementation_response = await Get(
            AlternateImplementationAck, PythonBinaryImplementation, alternate_impl_request)
        if alternate_implementation_response == AlternateImplementationAck.can_be_used:
            return await Get(CreatedBinary, PythonBinaryImplementation, alternate_impl_request)

    reduced_field_set = ReducedPythonBinaryFieldSet.from_real_field_set(field_set)
    entry_point = (
        await Get(PythonEntryPointWrapper, ReducedPythonBinaryFieldSet, reduced_field_set)
    ).value

    disambiguated_output_filename = os.path.join(
        field_set.address.spec_path.replace(os.sep, "."), f"{field_set.address.target_name}.pex"
    )
    if global_options.options.pants_distdir_legacy_paths:
        output_filename = f"{field_set.address.target_name}.pex"
        logger.warning(
            f"Writing to the legacy subpath: {output_filename}, which may not be unique. An "
            f"upcoming version of Pants will switch to writing to the fully-qualified subpath: "
            f"{disambiguated_output_filename}. You can effect that switch now (and silence this "
            f"warning) by setting `pants_distdir_legacy_paths = false` in the [GLOBAL] section of "
            f"pants.toml."
        )
    else:
        output_filename = disambiguated_output_filename
    two_step_pex = await Get(
        TwoStepPex,
        TwoStepPexFromTargetsRequest(
            PexFromTargetsRequest(
                addresses=[field_set.address],
                internal_only=False,
                entry_point=entry_point,
                platforms=PexPlatforms.create_from_platforms_field(field_set.platforms),
                output_filename=output_filename,
                additional_args=field_set.generate_additional_args(python_binary_defaults),
            )
        ),
    )
    pex = two_step_pex.pex
    return CreatedBinary(digest=pex.digest, binary_name=pex.name)


def rules():
    return [
        *collect_rules(),
        UnionRule(BinaryFieldSet, PythonBinaryFieldSet),
    ]
