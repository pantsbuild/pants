# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json

from pants.core.util_rules.external_tool import ExternalToolRequest
from pants.engine.fs import DownloadFile
from pants.engine.internals.native_engine import FileDigest
from pants.engine.platform import Platform
from pants.ng.subsystem import ContextualSubsystem, option
from pants.util.resources import read_resource
from pants.util.strutil import softwrap


class ExternalBinary(ContextualSubsystem):
    @option(help="Version of the binary to use", default=lambda cls: cls.version_default)
    def version(self) -> str: ...

    exe_help = softwrap(
        """
        The executable to invoke: the downloaded file itself, or if the download is an archive,
        the relative path of the executable file within that archive."
        """
    )

    @classmethod
    def exe_default(cls) -> str:
        raise NotImplementedError("Subclasses must implement to provide the default executable")


    @option(help=exe_help, default=lambda cls: cls.exe_default)
    def exe(self) -> str: ...

    known_versions_help = softwrap(
        """
        A JSON string containing metadata of all known versions of the binary:

        {
            "version1": {
                "platform1": {
                    "url": ...
                    "sha256": ...
                    "size": ...
                },
                "platform2": {
                    "url": ...
                    "sha256": ...
                    "size": ...
                },
            }
            "version2": ...
        }

        Where each platform is one of `linux_x86_64`, `linux_arm64` or `macos_arm64`.

        Can be a string of the form `@dotted.pkg:filename.json` to load the value from
        that file in that package.
        """
    )

    @option(help=known_versions_help, default=lambda cls: cls.known_versions_default)
    def known_versions(self) -> str: ...

    def get_download_request(self) -> ExternalToolRequest:
        known_versions = self.known_versions
        if known_versions.startswith("@"):
            pkg, _, filename = known_versions[1:].partition(":")
            known_versions = read_resource(pkg, filename)
        metadata = json.loads(known_versions.strip())
        version = self.version
        version_metadata = metadata.get(version)
        if not version_metadata:
            raise ValueError(
                f"No metadata for version {version} in known_versions for tool {self.options_scope}."
            )
        platform = Platform.create_for_localhost().name
        platform_metadata = version_metadata.get(platform)
        if not platform_metadata:
            raise ValueError(
                f"No metadata for version {version} on platform {platform} in known_versions for tool {self.options_scope}."
            )
        url = platform_metadata.get("url")
        if not url:
            raise ValueError(
                f"No url for version {version} on platform {platform} in known_versions for tool {self.options_scope}."
            )
        sha256 = platform_metadata.get("sha256")
        if not sha256:
            raise ValueError(
                f"No sha256 for version {version} on platform {platform} in known_versions for tool {self.options_scope}."
            )
        size = platform_metadata.get("size")
        if not size:
            raise ValueError(
                f"No size for version {version} on platform {platform} in known_versions for tool {self.options_scope}."
            )
        return ExternalToolRequest(
            download_file_request=DownloadFile(url=url, expected_digest=FileDigest(sha256, size)),
            exe=self.exe,
            strip_common_path_prefix=True,
        )
