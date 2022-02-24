# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import logging
import textwrap
from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, cast

from pkg_resources import Requirement

from pants.core.util_rules import archive
from pants.core.util_rules.archive import ExtractedArchive
from pants.engine.fs import CreateDigest, Digest, DigestEntries, DownloadFile, FileDigest, FileEntry
from pants.engine.platform import Platform
from pants.engine.rules import Get, collect_rules, rule
from pants.option.subsystem import Subsystem
from pants.util.docutil import doc_url
from pants.util.logging import LogLevel
from pants.util.meta import classproperty

logger = logging.getLogger(__name__)


class UnknownVersion(Exception):
    pass


class ExternalToolError(Exception):
    pass


class UnsupportedVersion(ExternalToolError):
    """The specified version of the tool is not supported, according to the given version
    constraints."""


class UnsupportedVersionUsage(Enum):
    """What action to take in case the requested version of the tool is not supported."""

    RaiseError = "error"
    LogWarning = "warning"


@dataclass(frozen=True)
class ExternalToolRequest:
    download_file_request: DownloadFile
    exe: str


@dataclass(frozen=True)
class DownloadedExternalTool:
    digest: Digest
    exe: str


class ExternalTool(Subsystem, metaclass=ABCMeta):
    """Configuration for an invocable tool that we download from an external source.

    Subclass this to configure a specific tool.


    Idiomatic use:

    class MyExternalTool(ExternalTool):
        options_scope = "my-external-tool"
        default_version = "1.2.3"
        default_known_versions = [
          "1.2.3|linux_arm64 |feed6789feed6789feed6789feed6789feed6789feed6789feed6789feed6789|112233",
          "1.2.3|linux_x86_64|cafebabacafebabacafebabacafebabacafebabacafebabacafebabacafebaba|878986",
          "1.2.3|macos_arm64 |deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef|222222",
          "1.2.3|macos_x86_64|1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd|333333",
        ]

        version_constraints = ">=1.2.3, <2.0"

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

    # The default values for --version and --known-versions, and the supported versions.
    # Subclasses must set appropriately.
    default_version: str
    default_known_versions: list[str]
    version_constraints: str | None = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.check_version_constraints()

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
            help=f"Use this version of {cls.name}."
            + (
                f"\n\nSupported {cls.name} versions: {cls.version_constraints}"
                if cls.version_constraints
                else ""
            ),
        )

        help_str = textwrap.dedent(
            f"""
            Known versions to verify downloads against.

            Each element is a pipe-separated string of `version|platform|sha256|length`, where:

              - `version` is the version string
              - `platform` is one of [{','.join(Platform.__members__.keys())}],
              - `sha256` is the 64-character hex representation of the expected sha256
                digest of the download file, as emitted by `shasum -a 256`
              - `length` is the expected length of the download file in bytes, as emitted by
                `wc -c`

            E.g., `3.1.2|macos_x86_64|6d0f18cd84b918c7b3edd0203e75569e0c7caecb1367bbbe409b44e28514f5be|42813`.

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

        register(
            "--use-unsupported-version",
            advanced=True,
            type=UnsupportedVersionUsage,
            help=textwrap.dedent(
                f"""
                What action to take in case the requested version of {cls.name} is not supported.

                Supported {cls.name} versions: {cls.version_constraints if cls.version_constraints else "unspecified"}
                """
            ),
            default=UnsupportedVersionUsage.RaiseError,
        )

    @property
    def version(self) -> str:
        return cast(str, self.options.version)

    @property
    def known_versions(self) -> tuple[str, ...]:
        return tuple(self.options.known_versions)

    @abstractmethod
    def generate_url(self, plat: Platform) -> str:
        """Returns the URL for the given version of the tool, runnable on the given os+arch.

        Implementations should raise ExternalToolError if they cannot resolve the arguments
        to a URL. The raised exception need not have a message - a sensible one will be generated.
        """

    def generate_exe(self, plat: Platform) -> str:
        """Returns the path to the tool executable.

        If the downloaded artifact is the executable itself, you can leave this unimplemented.

        If the downloaded artifact is an archive, this should be overridden to provide a
        relative path in the downloaded archive, e.g. `./bin/protoc`.
        """
        return f"./{self.generate_url(plat).rsplit('/', 1)[-1]}"

    def get_request(self, plat: Platform) -> ExternalToolRequest:
        """Generate a request for this tool."""
        for known_version in self.known_versions:
            ver, plat_val, sha256, length = self.split_known_version_str(known_version)
            if plat.value == plat_val and ver == self.version:
                return self.get_request_for(plat_val, sha256, length)
        raise UnknownVersion(
            f"No known version of {self.name} {self.version} for {plat.value} found in "
            f"{self.known_versions}"
        )

    @classmethod
    def split_known_version_str(cls, known_version: str) -> tuple[str, str, str, int]:
        try:
            ver, plat_val, sha256, length = (x.strip() for x in known_version.split("|"))
        except ValueError:
            raise ExternalToolError(
                f"Bad value for [{cls.options_scope}].known_versions: {known_version}"
            )
        return ver, plat_val, sha256, int(length)

    def get_request_for(self, plat_val: str, sha256: str, length: int) -> ExternalToolRequest:
        """Generate a request for this tool from the given info."""
        plat = Platform(plat_val)
        digest = FileDigest(fingerprint=sha256, serialized_bytes_length=length)
        try:
            url = self.generate_url(plat)
            exe = self.generate_exe(plat)
        except ExternalToolError as e:
            raise ExternalToolError(
                f"Couldn't find {self.name} version {self.version} on {plat.value}"
            ) from e
        return ExternalToolRequest(DownloadFile(url=url, expected_digest=digest), exe)

    def check_version_constraints(self) -> None:
        if not self.version_constraints:
            return None
        # Note that this is not a Python requirement. We're just hackily piggybacking off
        # pkg_resource.Requirement's ability to check version constraints.
        constraints = Requirement.parse(f"{self.name}{self.version_constraints}")
        if constraints.specifier.contains(self.version):  # type: ignore[attr-defined]
            # all ok
            return None

        msg = [
            f"The option [{self.options_scope}].version is set to {self.version}, which is not "
            f"compatible with what this release of Pants expects: {constraints}.",
            "Please update the version to a supported value, or consider using a different Pants",
            "release if you cannot change the version.",
        ]

        if self.options.use_unsupported_version is UnsupportedVersionUsage.LogWarning:
            msg.extend(
                [
                    "Alternatively, you can ignore this warning (at your own peril) by adding this",
                    "to the GLOBAL section of pants.toml:",
                    f'ignore_warnings = ["The option [{self.options_scope}].version is set to"].',
                ]
            )
            logger.warning(" ".join(msg))
        elif self.options.use_unsupported_version is UnsupportedVersionUsage.RaiseError:
            msg.append(
                f"Alternatively, update [{self.options_scope}].use_unsupported_version to be "
                f"'warning'."
            )
            raise UnsupportedVersion(" ".join(msg))


class TemplatedExternalTool(ExternalTool):
    """Extends the ExternalTool to allow url templating for custom/self-hosted source.

    In addition to ExternalTool functionalities, it is needed to set, e.g.:

    default_url_template = "https://tool.url/{version}/{platform}-mytool.zip"
    default_url_platform_mapping = {
        "macos_x86_64": "osx_intel",
        "macos_arm64": "osx_arm",
        "linux_x86_64": "linux",
    }

    The platform mapping dict is optional.
    """

    default_url_template: str
    default_url_platform_mapping: dict[str, str] | None = None

    @classmethod
    def register_options(cls, register):
        super().register_options(register)

        register(
            "--url-template",
            type=str,
            default=cls.default_url_template,
            advanced=True,
            help=(
                "URL to download the tool, either as a single binary file or a compressed file "
                "(e.g. zip file). You can change this to point to your own hosted file, e.g. to "
                "work with proxies or for access via the filesystem through a `file:$abspath` URL (e.g. "
                "`file:/this/is/absolute`, possibly by [templating the buildroot in a "
                f"config file]({doc_url('options#config-file-entries')})).\n\n"
                "Use `{version}` to have the value from --version substituted, and `{platform}` to "
                "have a value from --url-platform-mapping substituted in, depending on the "
                "current platform. For example, "
                "https://github.com/.../protoc-{version}-{platform}.zip."
            ),
        )

        register(
            "--url-platform-mapping",
            type=dict,
            default=cls.default_url_platform_mapping,
            advanced=True,
            help=(
                "A dictionary mapping platforms to strings to be used when generating the URL "
                "to download the tool.\n\nIn --url-template, anytime the `{platform}` string is "
                "used, Pants will determine the current platform, and substitute `{platform}` with "
                "the respective value from your dictionary.\n\nFor example, if you define "
                '`{"macos_x86_64": "apple-darwin", "linux_x86_64": "unknown-linux"}, and run Pants on '
                "Linux with an intel architecture, then `{platform}` will be substituted in the --url-template option with "
                "unknown-linux."
            ),
        )

    @property
    def url_template(self) -> str:
        return cast(str, self.options.url_template)

    @property
    def url_platform_mapping(self) -> dict[str, str] | None:
        return cast(Optional[Dict[str, str]], self.options.url_platform_mapping)

    def generate_url(self, plat: Platform):
        platform = self.url_platform_mapping[plat.value] if self.url_platform_mapping else ""
        return self.url_template.format(version=self.version, platform=platform)


@rule(level=LogLevel.DEBUG)
async def download_external_tool(request: ExternalToolRequest) -> DownloadedExternalTool:
    # Download and extract.
    maybe_archive_digest = await Get(Digest, DownloadFile, request.download_file_request)
    extracted_archive = await Get(ExtractedArchive, Digest, maybe_archive_digest)

    # Confirm executable.
    exe_path = request.exe.lstrip("./")
    digest = extracted_archive.digest
    is_not_executable = False
    digest_entries = []
    for entry in await Get(DigestEntries, Digest, digest):
        if isinstance(entry, FileEntry) and entry.path == exe_path and not entry.is_executable:
            # We should recreate the digest with the executable bit set.
            is_not_executable = True
            entry = dataclasses.replace(entry, is_executable=True)
        digest_entries.append(entry)
    if is_not_executable:
        digest = await Get(Digest, CreateDigest(digest_entries))

    return DownloadedExternalTool(digest, request.exe)


def rules():
    return (*collect_rules(), *archive.rules())
