# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

import nodesemver

from pants.util.frozendict import FrozenDict


@dataclass(frozen=True)
class PackageManager:
    name: str
    version: str | None
    lockfile_name: str
    generate_lockfile_args: tuple[str, ...]
    immutable_install_args: tuple[str, ...]
    workspace_specifier_arg: str
    run_arg_separator: tuple[str, ...]
    download_and_execute_args: tuple[str, ...]
    execute_args: tuple[str, ...]
    current_directory_args: tuple[str, ...]

    extra_env: FrozenDict[str, str]
    pack_archive_format: str
    extra_caches: FrozenDict[str, str]

    @classmethod
    def from_string(cls, string: str) -> PackageManager:
        package_manager_command, *maybe_version = string.split("@")
        package_manager_version = maybe_version[0] if maybe_version else None
        if package_manager_command == "npm":
            return cls.npm(package_manager_version)
        if package_manager_command == "yarn":
            return cls.yarn(package_manager_version)
        if package_manager_command == "pnpm":
            return cls.pnpm(package_manager_version)
        raise ValueError(f"Unsupported package manager: {package_manager_command}.")

    @classmethod
    def pnpm(cls, version: str | None) -> PackageManager:
        return PackageManager(
            name="pnpm",
            version=version,
            lockfile_name="pnpm-lock.yaml",
            generate_lockfile_args=("install", "--lockfile-only"),
            immutable_install_args=("install", "--frozen-lockfile"),
            workspace_specifier_arg="--filter",
            run_arg_separator=(
                () if version is None or nodesemver.satisfies(version, ">=7") else ("--",)
            ),
            download_and_execute_args=("dlx",),
            execute_args=("exec",),
            current_directory_args=("--prefix",),
            extra_env=FrozenDict({"PNPM_HOME": "{chroot}/._pnpm_home"}),
            pack_archive_format="{}-{}.tgz",
            extra_caches=FrozenDict({"pnpm_home": "._pnpm_home"}),
        )

    @classmethod
    def yarn(cls, version: str | None) -> PackageManager:
        return PackageManager(
            name="yarn",
            version=version,
            lockfile_name="yarn.lock",
            generate_lockfile_args=("install",),
            immutable_install_args=(
                ("install", "--frozen-lockfile")
                if version is None or nodesemver.satisfies(version, "1.x")
                else ("install", "--immutable")
            ),
            workspace_specifier_arg="workspace",
            run_arg_separator=("--",),
            download_and_execute_args=("dlx", "--quiet"),
            execute_args=("--silent", "exec", "--"),
            current_directory_args=("--cwd",),
            extra_env=FrozenDict({"YARN_CACHE_FOLDER": "{chroot}/._yarn_cache"}),
            pack_archive_format="{}-v{}.tgz",
            extra_caches=FrozenDict({"yarn_cache": "._yarn_cache"}),
        )

    @classmethod
    def npm(cls, version: str | None) -> PackageManager:
        return PackageManager(
            name="npm",
            version=version,
            lockfile_name="package-lock.json",
            generate_lockfile_args=("install", "--package-lock-only"),
            immutable_install_args=("clean-install",),
            workspace_specifier_arg="--workspace",
            run_arg_separator=("--",),
            download_and_execute_args=("exec", "--yes", "--"),
            execute_args=("exec", "--no", "--"),
            current_directory_args=("--prefix",),
            extra_env=FrozenDict(),
            pack_archive_format="{}-{}.tgz",
            extra_caches=FrozenDict(),
        )
