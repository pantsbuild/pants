# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from pants.engine.environment import Environment, EnvironmentRequest
from pants.engine.fs import EMPTY_DIGEST, Digest
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import (
    BinaryNotFoundError,
    BinaryPath,
    BinaryPathRequest,
    BinaryPaths,
    BinaryPathTest,
    Process,
    ProcessCacheScope,
    ProcessResult,
)
from pants.engine.rules import collect_rules, rule
from pants.option.subsystem import Subsystem
from pants.util.logging import LogLevel
from pants.util.ordered_set import OrderedSet

logger = logging.getLogger(__name__)


class TerraformSubsystem(Subsystem):
    options_scope = "terraform"
    help = "Terraform (https://terraform.io)"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)

        register(
            "--search-paths",
            type=list,
            member_type=str,
            default=[],
            help=(
                "A list of paths to search for Terraform.\n\n"
                "Specify absolute paths to directories with the `terraform` binary, e.g. `/usr/bin`. "
                "Earlier entries will be searched first.\n\n"
                "The special string '<PATH>' will expand to the contents of the PATH env var."
            ),
        )

        register(
            "--version-constraint",
            type=str,
            default=">=1.0",
            help=(
                "One or more semantic version constraints separated by commas used to filter the Terraform "
                "binaries found by searching `[terraform].search_paths`. For example, to use only 1.0.x releases "
                "of Terraform, the version constraint could be `>=1.0.0,<1.1`."
            ),
        )

    @property
    def version_constraint_set(self) -> SpecifierSet:
        try:
            return SpecifierSet(self.options.version_constraint)
        except InvalidSpecifier as ex:
            raise ValueError(
                f"The --terraform-version-constraint option {self.options.version_constraint} contained "
                f"an invalid specifier: {ex}"
            )

    def search_paths(self, env: Environment) -> tuple[str, ...]:
        def iter_path_entries():
            for entry in self.options.search_paths:
                if entry == "<PATH>":
                    path = env.get("PATH")
                    if path:
                        for path_entry in path.split(os.pathsep):
                            yield path_entry
                else:
                    yield entry

        return tuple(OrderedSet(iter_path_entries()))


@dataclass(frozen=True)
class TerraformSetup:
    path: BinaryPath


@rule
async def find_terraform(terraform: TerraformSubsystem) -> TerraformSetup:
    env = await Get(Environment, EnvironmentRequest(["PATH"]))
    search_paths = terraform.search_paths(env)

    all_terraform_binary_paths = await Get(
        BinaryPaths,
        BinaryPathRequest(
            search_path=search_paths,
            binary_name="terraform",
            test=BinaryPathTest(["version"]),
        ),
    )

    if not all_terraform_binary_paths.paths:
        raise BinaryNotFoundError(
            "Cannot find any `terraform` binaries using the option "
            f"`[terraform].search_paths`: {list(search_paths)}\n\n"
            "To fix, please install Terraform and ensure that the `terraform` binary "
            "is discoverable via `[terraform].search_paths`."
        )

    version_results = await MultiGet(
        Get(
            ProcessResult,
            Process(
                (binary_path.path, "version"),
                description=f"Determine Terraform version for {binary_path.path}",
                level=LogLevel.DEBUG,
                cache_scope=ProcessCacheScope.PER_RESTART_SUCCESSFUL,
            ),
        )
        for binary_path in all_terraform_binary_paths.paths
    )

    constraints_set = terraform.version_constraint_set

    invalid_versions = []
    for binary_path, version_result in zip(all_terraform_binary_paths.paths, version_results):
        try:
            version = Version(version_result.stdout.decode("utf-8").strip())
        except InvalidVersion:
            raise AssertionError(
                f"Failed to parse `terraform version` output for {binary_path}. Please open an issue at "
                f"https://github.com/pantsbuild/pants/issues/new/choose with the below data."
                f"\n\n"
                f"{version_result}"
            )

        if constraints_set.contains(version):
            return TerraformSetup(binary_path)

        invalid_versions.append((binary_path.path, version))

    bulleted_list_sep = "\n  * "
    invalid_versions_str = bulleted_list_sep.join(
        f"{path}: {version}" for path, version in sorted(invalid_versions)
    )
    raise BinaryNotFoundError(
        "Cannot find a `terraform` binary which satisfies the version constraint "
        f"`{terraform.options.version_constraint}`.\n\n"
        f"Found these `terraform` binaries, but they had versions which did not match that constraint:\n"
        f"{bulleted_list_sep}{invalid_versions_str}\n\n"
        "To fix, please install a matching version (https://terraform.io) and ensure "
        "that it is discoverable via the option `[terraform].search_paths`, or change "
        "`[terraform].version_constraint`."
    )


@dataclass(frozen=True)
class TerraformProcess:
    """A request to invoke Terraform."""

    args: tuple[str, ...]
    description: str
    input_digest: Digest = EMPTY_DIGEST
    output_files: tuple[str, ...] = ()


@rule
async def setup_terraform_process(
    request: TerraformProcess, terraform_setup: TerraformSetup
) -> Process:
    return Process(
        argv=(terraform_setup.path.path,) + request.args,
        input_digest=request.input_digest,
        output_files=request.output_files,
        description=request.description,
        level=LogLevel.DEBUG,
    )


def rules():
    return collect_rules()
