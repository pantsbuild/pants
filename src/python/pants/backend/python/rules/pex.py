# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import ClassVar, Iterable, List, Optional, Tuple

from pants.backend.python.rules.download_pex_bin import DownloadedPexBin
from pants.backend.python.rules.hermetic_pex import HermeticPex
from pants.backend.python.subsystems.python_native_code import PexBuildEnvironment
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.engine.fs import (
    EMPTY_DIRECTORY_DIGEST,
    Digest,
    DirectoriesToMerge,
    DirectoryWithPrefixToAdd,
    FileContent,
    InputFilesContent,
)
from pants.engine.isolated_process import ExecuteProcessResult, MultiPlatformExecuteProcessRequest
from pants.engine.legacy.structs import PythonTargetAdaptor, TargetAdaptor
from pants.engine.platform import Platform, PlatformConstraint
from pants.engine.rules import rule, subsystem_rule
from pants.engine.selectors import Get
from pants.python.python_setup import PythonSetup


@dataclass(frozen=True)
class PexRequirements:
    requirements: Tuple[str, ...] = ()

    @classmethod
    def create_from_adaptors(
        cls, adaptors: Iterable[TargetAdaptor], additional_requirements: Iterable[str] = ()
    ) -> "PexRequirements":
        all_target_requirements = set()
        for maybe_python_req_lib in adaptors:
            # This is a python_requirement()-like target.
            if hasattr(maybe_python_req_lib, "requirement"):
                all_target_requirements.add(str(maybe_python_req_lib.requirement))
            # This is a python_requirement_library()-like target.
            if hasattr(maybe_python_req_lib, "requirements"):
                for py_req in maybe_python_req_lib.requirements:
                    all_target_requirements.add(str(py_req.requirement))
        all_target_requirements.update(additional_requirements)
        return PexRequirements(requirements=tuple(sorted(all_target_requirements)))


@dataclass(frozen=True)
class PexInterpreterConstraints:
    constraint_set: Tuple[str, ...] = ()

    def generate_pex_arg_list(self) -> List[str]:
        args = []
        for constraint in sorted(self.constraint_set):
            args.extend(["--interpreter-constraint", constraint])
        return args

    @classmethod
    def create_from_adaptors(
        cls, adaptors: Iterable[PythonTargetAdaptor], python_setup: PythonSetup
    ) -> "PexInterpreterConstraints":
        interpreter_constraints = {
            constraint
            for target_adaptor in adaptors
            for constraint in python_setup.compatibility_or_constraints(
                getattr(target_adaptor, "compatibility", None)
            )
        }
        return PexInterpreterConstraints(constraint_set=tuple(sorted(interpreter_constraints)))


@dataclass(unsafe_hash=True)
class PexRequirementConstraints:
    """A collection of Requirement-style strings."""

    constraints: Tuple[str, ...] = ()
    generated_file_name: ClassVar[str] = "requirement_constraints.generated.txt"

    @classmethod
    def create_from_setup(cls, python_setup: PythonSetup) -> "PexRequirementConstraints":
        return cls(python_setup.requirement_constraints)

    def generate_pex_arg_list(self) -> List[str]:
        if not self.constraints:
            return []
        return ["--constraints", self.generated_file_name]

    def generate_constraints_file(self) -> InputFilesContent:
        if not self.constraints:
            return InputFilesContent([])
        generated_file = FileContent(
            path=self.generated_file_name, content="\n".join(self.constraints).encode()
        )
        return InputFilesContent([generated_file])


@dataclass(frozen=True)
class CreatePex:
    """Represents a generic request to create a PEX from its inputs."""

    output_filename: str
    requirements: PexRequirements = PexRequirements()
    interpreter_constraints: PexInterpreterConstraints = PexInterpreterConstraints()
    requirement_constraints: PexRequirementConstraints = PexRequirementConstraints()
    entry_point: Optional[str] = None
    input_files_digest: Optional[Digest] = None
    additional_args: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Pex(HermeticPex):
    """Wrapper for a digest containing a pex file created with some filename."""

    directory_digest: Digest
    output_filename: str


@rule(name="Create PEX")
async def create_pex(
    request: CreatePex,
    pex_bin: DownloadedPexBin,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
    pex_build_environment: PexBuildEnvironment,
    platform: Platform,
) -> Pex:
    """Returns a PEX with the given requirements, optional entry point, optional interpreter
    constraints, and optional requirement constraints."""

    argv = [
        "--output-file",
        request.output_filename,
        *request.interpreter_constraints.generate_pex_arg_list(),
        *request.requirement_constraints.generate_pex_arg_list(),
        *request.additional_args,
    ]

    if python_setup.resolver_jobs:
        argv.extend(["--jobs", python_setup.resolver_jobs])

    if python_setup.manylinux:
        argv.extend(["--manylinux", python_setup.manylinux])
    else:
        argv.append("--no-manylinux")

    if request.entry_point is not None:
        argv.extend(["--entry-point", request.entry_point])

    source_dir_name = "source_files"
    argv.append(f"--sources-directory={source_dir_name}")

    argv.extend(request.requirements.requirements)

    generated_constraint_file = await Get[Digest](
        InputFilesContent, request.requirement_constraints.generate_constraints_file()
    )

    sources_digest = (
        request.input_files_digest if request.input_files_digest else EMPTY_DIRECTORY_DIGEST
    )
    sources_digest_as_subdir = await Get[Digest](
        DirectoryWithPrefixToAdd(sources_digest, source_dir_name)
    )

    merged_digest = await Get[Digest](
        DirectoriesToMerge(
            directories=(
                pex_bin.directory_digest,
                sources_digest_as_subdir,
                generated_constraint_file,
            )
        )
    )

    # NB: PEX outputs are platform dependent so in order to get a PEX that we can use locally, without
    # cross-building, we specify that our PEX command be run on the current local platform. When we
    # support cross-building through CLI flags we can configure requests that build a PEX for our
    # local platform that are able to execute on a different platform, but for now in order to
    # guarantee correct build we need to restrict this command to execute on the same platform type
    # that the output is intended for. The correct way to interpret the keys
    # (execution_platform_constraint, target_platform_constraint) of this dictionary is "The output of
    # this command is intended for `target_platform_constraint` iff it is run on `execution_platform
    # constraint`".
    execute_process_request = MultiPlatformExecuteProcessRequest(
        {
            (
                PlatformConstraint(platform.value),
                PlatformConstraint(platform.value),
            ): pex_bin.create_execute_request(
                python_setup=python_setup,
                subprocess_encoding_environment=subprocess_encoding_environment,
                pex_build_environment=pex_build_environment,
                pex_args=argv,
                input_files=merged_digest,
                description=f"Create a requirements PEX: {', '.join(request.requirements.requirements)}",
                output_files=(request.output_filename,),
            )
        }
    )

    result = await Get[ExecuteProcessResult](
        MultiPlatformExecuteProcessRequest, execute_process_request
    )
    return Pex(
        directory_digest=result.output_directory_digest, output_filename=request.output_filename
    )


def rules():
    return [
        create_pex,
        subsystem_rule(PythonSetup),
    ]
