# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import textwrap
from abc import abstractmethod
from dataclasses import dataclass
from typing import List, Tuple, cast

from pants.core.util_rules.archive import ExtractedDigest, MaybeExtractable
from pants.engine.fs import Digest, DownloadFile
from pants.engine.platform import Platform
from pants.engine.rules import Get, RootRule, collect_rules, rule
from pants.option.subsystem import Subsystem
from pants.util.meta import classproperty


class UnknownVersion(Exception):
    pass


class ExternalToolError(Exception):
    pass


@dataclass(frozen=True)
class ExternalToolRequest:
    download_file_request: DownloadFile
    exe: str


@dataclass(frozen=True)
class DownloadedExternalTool:
    digest: Digest
    exe: str


class ExternalTool(Subsystem):
    """Configuration for an invocable tool that we download from an external source.

    Subclass this to configure a specific tool.


    Idiomatic use:

    class MyExternalTool(ExternalTool):
        options_scope = "my-external-tool"
        default_version = "1.2.3"
        default_known_versions = [
          "1.2.3|darwin|deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef|222222",
          "1.2.3|linux |1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd|333333",
        ]

        def generate_url(self, plat: Platform) -> str:
            ...

        def generate_exe(self, plat: Platform) -> str:
            return "./path-to/binary

    @rule
    def my_rule(my_external_tool: MyExternalTool) -> Foo:
        downloaded_tool = await Get(
            DownloadedExternalTool,
            ExternalToolRequest,
            my_external_tool.get_request(Platform.current)
        )
        ...
    """

    # The default values for --version and --known-versions.
    # Subclasses must set appropriately.
    default_version: str
    default_known_versions: List[str]

    @classproperty
    def name(cls):
        """The name of the tool, for use in user-facing messages.

        Derived from the classname, but subclasses can override, e.g., with a classproperty.
        """
        return cls.__name__.lower()

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--version",
            type=str,
            default=cls.default_version,
            advanced=True,
            help=f"Use this version of {cls.name}.",
        )

        help_str = textwrap.dedent(
            f"""
            Known versions to verify downloads against.

            Each element is a pipe-separated string of `version|platform|sha256|length`, where:

              - `version` is the version string
              - `platform` is one of [{','.join(Platform.__members__.keys())}],
              - `sha256` is the 64-character hex representation of the expected sha256
                digest of the download file, as emitted by `shasum -a 256`
              - `length` is the expected length of the download file in bytes

            E.g., `3.1.2|darwin|6d0f18cd84b918c7b3edd0203e75569e0c7caecb1367bbbe409b44e28514f5be|42813`.

            Values are space-stripped, so pipes can be indented for readability if necessary.
            """
        )
        # Note that you can compute the length and sha256 conveniently with:
        #   `curl -L $URL | tee >(wc -c) >(shasum -a 256) >/dev/null`
        register(
            "--known-versions",
            type=list,
            member_type=str,
            default=cls.default_known_versions,
            advanced=True,
            help=help_str,
        )

    @property
    def version(self) -> str:
        return cast(str, self.options.version)

    @property
    def known_versions(self) -> Tuple[str, ...]:
        return tuple(self.options.known_versions)

    @abstractmethod
    def generate_url(self, plat: Platform) -> str:
        """Returns the URL for the given version of the tool, runnable on the given os+arch.

        os and arch default to those of the current system.

        Implementations should raise ExternalToolError if they cannot resolve the arguments
        to a URL. The raised exception need not have a message - a sensible one will be generated.
        """

    @abstractmethod
    def generate_exe(self, plat: Platform) -> str:
        """Returns the relative path in the downloaded archive to the given version of the tool,
        e.g. `./bin/protoc`."""

    def get_request(self, plat: Platform) -> ExternalToolRequest:
        """Generate a request for this tool."""
        for known_version in self.known_versions:
            try:
                ver, plat_val, sha256, length = (x.strip() for x in known_version.split("|"))
            except ValueError:
                raise ExternalToolError(
                    f"Bad value for --known-versions (see {self.options.pants_bin_name} "
                    f"help-advanced {self.options_scope}): {known_version}"
                )
            if plat_val == plat.value and ver == self.version:
                digest = Digest(fingerprint=sha256, serialized_bytes_length=int(length))
                try:
                    url = self.generate_url(plat)
                    exe = self.generate_exe(plat)
                except ExternalToolError as e:
                    raise ExternalToolError(
                        f"Couldn't find {self.name} version {self.version} on {plat.value}"
                    ) from e
                return ExternalToolRequest(DownloadFile(url=url, expected_digest=digest), exe)
        raise UnknownVersion(
            f"No known version of {self.name} {self.version} for {plat.value} found in "
            f"{self.known_versions}"
        )


@rule
async def download_external_tool(request: ExternalToolRequest) -> DownloadedExternalTool:
    digest = await Get(Digest, DownloadFile, request.download_file_request)
    extracted_digest = await Get(ExtractedDigest, MaybeExtractable(digest))
    return DownloadedExternalTool(extracted_digest.digest, request.exe)


def rules():
    return [*collect_rules(), RootRule(ExternalToolRequest)]
