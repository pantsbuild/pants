# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from textwrap import dedent

from pants.backend.rust.subsystems.cargo import Cargo
from pants.backend.rust.subsystems.rust_toolchain import RustToolchain
from pants.backend.rust.subsystems.rustup import Rustup
from pants.base.build_root import BuildRoot
from pants.build_graph.address import Address
from pants.core.util_rules.distdir import DistDir
from pants.engine.addresses import Addresses
from pants.engine.console import Console
from pants.engine.fs import (
    AddPrefix, Digest, DirectoryToMaterialize, FileContent, FilesContent,
    InputFilesContent, MergeDigests, MergedResult, MergeMaybeDuplicates, RemovePrefix, PathGlobs,
    Snapshot, SnapshotSubset, Workspace)
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import RootRule, goal_rule, rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import HydrateSourcesRequest, HydratedSources, Sources, Target, Targets


@dataclass(frozen=True)
class SingleCargoTarget:
    unprefixed_sources: Snapshot

    @property
    def digest(self) -> Digest:
        return self.unprefixed_sources.digest


@rule
async def fetch_cargo_packages(single_target: SingleCargoTarget) -> FetchedCargoPackages:
    lockfile_snapshot = await Get[Snapshot](SnapshotSubset(
        digest=single_target.digest,
        globs=PathGlobs(['Cargo.lock'])))
    assert lockfile_snapshot.files == ('Cargo.lock',), f'snap: {lockfile_snapshot}'
    (lockfile_content,) = tuple(await Get[FilesContent](Digest, lockfile_snapshot.digest))
    return await Get[FetchedCargoPackages](CargoLockfile(
        contents=lockfile_content.content.decode(),
    ))


@dataclass(frozen=True)
class CargoToolchainChroot:
    merged_digest: Digest


@rule
async def create_cargo_toolchain_chroot(
    fetched_packages: FetchedCargoPackages,
    rust_toolchain: RustToolchain,
) -> CargoToolchainChroot:
    crate_digests = list(fetched_packages.krate_mapping.values())
    index_digest = fetched_packages.current_registry_index_digest
    merged_cargo_home = await Get[Digest](MergeDigests((
        *crate_digests,
        index_digest,
    )))
    # This is intended to ensure that the CARGO_HOME from the downloaded 3rdparty deps merges with
    # the one from the rust toolchain (which contains the cargo binary!)!
    prefixed_cargo_home = await Get[Digest](AddPrefix(
        digest=merged_cargo_home,
        prefix="cargo"))

    rust_toolchain_default_sentinel_file = await Get[Digest](InputFilesContent((FileContent(
        content=f'{rust_toolchain.version}\n'.encode(),
        path='rust-toolchain',
    ),)))

    merged = await Get[MergedResult](MergeMaybeDuplicates((
        rust_toolchain.snapshot,
        (await Get[Snapshot](Digest, prefixed_cargo_home)),
        (await Get[Snapshot](Digest, rust_toolchain_default_sentinel_file)),
    )))
    return CargoToolchainChroot(merged.snapshot.digest)


@dataclass(frozen=True)
class SourcesAndToolchainChroot:
    merged_digest: Digest


@rule
async def get_cargo_chroot_for_target(
    address: Address,
    rust_toolchain: RustToolchain,
) -> SourcesAndToolchainChroot:
    target = (await Get[Targets](Addresses((address,)))).expect_single()
    sources_from_buildroot = await Get[HydratedSources](HydrateSourcesRequest(target.get(Sources)))
    sources = await Get[Snapshot](RemovePrefix(
        digest=sources_from_buildroot.snapshot.digest,
        prefix=target.address.spec_path,
    ))

    # Assert that there is a Cargo.toml and a Cargo.lock file at the target's root.
    assert 'Cargo.toml' in sources.files, f'Cargo.toml for target {target} was not found -- were: {sources.files}'
    assert 'Cargo.lock' in sources.files, f'Cargo.lock for target {target} was not found -- were: {sources.files}'

    toolchain = await Get[CargoToolchainChroot](SingleCargoTarget(sources))
    merged = await Get[Digest](MergeDigests((toolchain.merged_digest, sources.digest)))
    return SourcesAndToolchainChroot(merged)


class CreateCargoChrootOptions(GoalSubsystem):
    """idk???"""
    name = 'create-cargo-chroot'


class CreateCargoChroot(Goal):
    subsystem_cls = CreateCargoChrootOptions


@goal_rule
async def cargo_chroot_goal(
    console: Console,
    addresses: Addresses,
    dist_dir: DistDir,
    build_root: BuildRoot,
    workspace: Workspace,
) -> CreateCargoChroot:
    single_address = addresses.as_single()
    assert single_address is not None, f'exactly one target address can be provided for this goal. addresses were: {addresses}'
    cargo_chroot = await Get[SourcesAndToolchainChroot](Address, single_address)

    workspace.materialize_directory(
        DirectoryToMaterialize(cargo_chroot.merged_digest,
                               path_prefix=str(dist_dir.relpath))
    )
    console.print_stdout(str(build_root.pathlib_path / dist_dir.relpath))

    return CreateCargoChroot(exit_code=0)


def rules():
    return [
        RootRule(SingleCargoTarget),
        fetch_cargo_packages,
        create_cargo_toolchain_chroot,
        get_cargo_chroot_for_target,
        cargo_chroot_goal,
    ]
