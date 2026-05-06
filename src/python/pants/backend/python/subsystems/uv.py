# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import ClassVar

from pants.core.util_rules.external_tool import (
    TemplatedExternalTool,
    download_external_tool,
)
from pants.engine.fs import Digest
from pants.engine.internals.native_engine import FrozenDict
from pants.engine.platform import Platform
from pants.engine.rules import collect_rules, rule
from pants.option.option_types import StrListOption
from pants.option.subsystem import Subsystem
from pants.util.memo import memoized_property
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import softwrap


class Uv(TemplatedExternalTool):
    options_scope = "uv"
    name = "uv"
    help = "The uv Python package manager (https://github.com/astral-sh/uv)."

    default_version = "0.11.6"
    default_known_versions = [
        "0.11.6|macos_arm64 |4b69a4e366ec38cd5f305707de95e12951181c448679a00dce2a78868dfc9f5b|20807020",
        "0.11.6|linux_x86_64|aa342a53abe42364093506d7704214d2cdca30b916843e520bc67759a5d20132|24460747",
        "0.11.6|linux_arm64 |d14ebd6f200047264152daaf97b8bd36c7885a5033e9e8bba8366cb0049c0d00|22576913",
    ]
    version_constraints = ">=0.7.4,<1.0"

    default_url_template = (
        "https://github.com/astral-sh/uv/releases/download/{version}/uv-{platform}.tar.gz"
    )
    default_url_platform_mapping = {
        "linux_arm64": "aarch64-unknown-linux-musl",
        "linux_x86_64": "x86_64-unknown-linux-musl",
        "macos_arm64": "aarch64-apple-darwin",
    }

    def generate_exe(self, plat: Platform) -> str:
        platform = self.default_url_platform_mapping[plat.value]
        return f"./uv-{platform}/uv"

    class EnvironmentAware(Subsystem.EnvironmentAware):
        env_vars_used_by_options = ("PATH",)

        _executable_search_paths = StrListOption(
            default=["<PATH>"],
            help=softwrap(
                """
                The PATH value that will be used by the uv subprocess and any subprocesses it
                spawns.

                The special string `"<PATH>"` will expand to the contents of the PATH env var.
                """
            ),
            advanced=True,
            metavar="<binary-paths>",
        )

        @memoized_property
        def path(self) -> tuple[str, ...]:
            def iter_path_entries():
                for entry in self._executable_search_paths:
                    if entry == "<PATH>":
                        path = self._options_env.get("PATH")
                        if path:
                            yield from path.split(os.pathsep)
                    else:
                        yield entry

            return tuple(OrderedSet(iter_path_entries()))


@dataclass(frozen=True)
class DownloadedUv:
    digest: Digest
    exe: str

    # The relpath to the named_cache inside the sandbox.
    cache_dir: ClassVar[str] = ".cache/uv_cache/"

    # Initial command line args for all invocations of this uv.
    # Callers will want to add further args for specific invocations.
    def args(self) -> tuple[str, ...]:
        return (
            self.exe,
            # --no-config suppresses user and host config discovery.
            "--no-config",
            # --config-file forces use of our generated uv.toml instead.
            "--config-file=uv.toml",
            f"--cache-dir={self.cache_dir}",
        )

    @classmethod
    def append_only_caches(cls) -> FrozenDict[str, str]:
        return FrozenDict({"uv_cache": cls.cache_dir})


@rule
async def download_uv_binary(uv: Uv, platform: Platform) -> DownloadedUv:
    downloaded = await download_external_tool(uv.get_request(platform))
    return DownloadedUv(
        digest=downloaded.digest,
        exe=downloaded.exe,
    )


def rules():
    return collect_rules()
