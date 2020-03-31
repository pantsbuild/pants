# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.binaries.binary_tool import BinaryToolFetchRequest, Script, ToolForPlatform, ToolVersion
from pants.binaries.binary_util import BinaryToolUrlGenerator
from pants.engine.fs import Digest, SingleFileExecutable, Snapshot
from pants.engine.isolated_process import ExecuteProcessRequest
from pants.engine.platform import PlatformConstraint
from pants.engine.rules import rule, subsystem_rule
from pants.engine.selectors import Get


class PexBinUrlGenerator(BinaryToolUrlGenerator):
    def generate_urls(self, version, host_platform):
        return [f"https://github.com/pantsbuild/pex/releases/download/{version}/pex"]


@dataclass(frozen=True)
class PexBinExecuteRequest:
    exe_req: ExecuteProcessRequest


@dataclass(frozen=True)
class DownloadedPexBin:
    exe: SingleFileExecutable

    @property
    def executable(self) -> str:
        return self.exe.exe_filename

    @property
    def directory_digest(self) -> Digest:
        return self.exe.directory_digest

    class Factory(Script):
        options_scope = "download-pex-bin"
        name = "pex"
        default_version = "v2.1.7"

        # Note: You can compute the digest and size using:
        # curl -L https://github.com/pantsbuild/pex/releases/download/vX.Y.Z/pex | tee >(wc -c) >(shasum -a 256) >/dev/null
        default_versions_and_digests = {
            PlatformConstraint.none: ToolForPlatform(
                digest=Digest(
                    "375ab4a405a6db57f3afd8d60eca666e61931b44f156dc78ac7d8e47bddc96d6", 2620451
                ),
                version=ToolVersion("v2.1.7"),
            ),
        }

        def get_external_url_generator(self):
            return PexBinUrlGenerator()


@rule
async def download_pex_bin(pex_binary_tool: DownloadedPexBin.Factory) -> DownloadedPexBin:
    snapshot = await Get[Snapshot](BinaryToolFetchRequest(pex_binary_tool))
    return DownloadedPexBin(SingleFileExecutable(snapshot))


def rules():
    return [
        download_pex_bin,
        subsystem_rule(DownloadedPexBin.Factory),
    ]
