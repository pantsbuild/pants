# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import logging
import os
import textwrap
from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
from enum import Enum

from packaging.requirements import Requirement

from pants.core.goals.export import (
    ExportedBinary,
    ExportRequest,
    ExportResult,
    ExportResults,
    ExportSubsystem,
)
from pants.core.goals.resolves import ExportableTool, ExportMode
from pants.core.util_rules import archive
from pants.core.util_rules.archive import maybe_extract_archive
from pants.engine.download_file import download_file
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import CreateDigest, Digest, DownloadFile, FileDigest, FileEntry
from pants.engine.internals.native_engine import RemovePrefix
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import create_digest, get_digest_entries, remove_prefix
from pants.engine.platform import Platform
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.unions import UnionMembership, UnionRule
from pants.option.option_types import DictOption, EnumOption, StrListOption, StrOption
from pants.option.subsystem import Subsystem, _construct_subsystem
from pants.util.docutil import doc_url
from pants.util.logging import LogLevel
from pants.util.meta import classproperty
from pants.util.strutil import softwrap

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
    # Some archive files for tools may have a common path prefix, e.g., representing the platform.
    # If this field is set, strip the common path prefix. If the archive contains just one file
    # will strip all dirs from that file.
    strip_common_path_prefix: bool = False


@dataclass(frozen=True)
class DownloadedExternalTool:
    digest: Digest
    exe: str


@dataclass(frozen=True)
class ExternalToolVersion:
    version: str
    platform: str
    sha256: str
    filesize: int
    url_override: str | None = None

    def encode(self) -> str:
        parts = [self.version, self.platform, self.sha256, str(self.filesize)]
        if self.url_override:
            parts.append(self.url_override)
        return "|".join(parts)

    @classmethod
    def decode(cls, version_str: str) -> ExternalToolVersion:
        parts = [x.strip() for x in version_str.split("|")]
        version, platform, sha256, filesize = parts[:4]
        url_override = parts[4] if len(parts) > 4 else None
        return cls(version, platform, sha256, int(filesize), url_override=url_override)


class ExternalToolOptionsMixin:
    """Common options for implementing subsystem providing an `ExternalToolRequest`."""

    @classproperty
    def name(cls):
        """The name of the tool, for use in user-facing messages.

        Derived from the classname, but subclasses can override, e.g., with a classproperty.
        """
        return cls.__name__.lower()

    @classproperty
    def binary_name(cls):
        """The name of the binary, as it normally known.

        This allows renaming a built binary to what users expect, even when the name is different.
        For example, the binary might be "taplo-linux-x86_64" and the name "Taplo", but users expect
        just "taplo".
        """
        return cls.name.lower()

    # The default values for --version and --known-versions, and the supported versions.
    # Subclasses must set appropriately.
    default_version: str
    default_known_versions: list[str]
    version_constraints: str | None = None

    version = StrOption(
        default=lambda cls: cls.default_version,
        advanced=True,
        help=lambda cls: f"Use this version of {cls.name}."
        + (
            f"\n\nSupported {cls.name} versions: {cls.version_constraints}"
            if cls.version_constraints
            else ""
        ),
    )

    # Note that you can compute the length and sha256 conveniently with:
    #   `curl -L $URL | tee >(wc -c) >(shasum -a 256) >/dev/null`
    known_versions = StrListOption(
        default=lambda cls: cls.default_known_versions,
        advanced=True,
        help=textwrap.dedent(
            f"""
        Known versions to verify downloads against.

        Each element is a pipe-separated string of `version|platform|sha256|length` or
        `version|platform|sha256|length|url_override`, where:

          - `version` is the version string
          - `platform` is one of `[{",".join(Platform.__members__.keys())}]`
          - `sha256` is the 64-character hex representation of the expected sha256
            digest of the download file, as emitted by `shasum -a 256`
          - `length` is the expected length of the download file in bytes, as emitted by
            `wc -c`
          - (Optional) `url_override` is a specific url to use instead of the normally
            generated url for this version

        E.g., `3.1.2|macos_x86_64|6d0f18cd84b918c7b3edd0203e75569e0c7caecb1367bbbe409b44e28514f5be|42813`.
        and `3.1.2|macos_arm64 |aca5c1da0192e2fd46b7b55ab290a92c5f07309e7b0ebf4e45ba95731ae98291|50926|https://example.mac.org/bin/v3.1.2/mac-aarch64-v3.1.2.tgz`.

        Values are space-stripped, so pipes can be indented for readability if necessary.
        """
        ),
    )


class ExternalTool(Subsystem, ExportableTool, ExternalToolOptionsMixin, metaclass=ABCMeta):
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
    async def my_rule(my_external_tool: MyExternalTool, platform: Platform) -> Foo:
        downloaded_tool = await download_external_tool(my_external_tool.get_request(platform))
        ...
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.check_version_constraints()

    export_mode = ExportMode.binary

    use_unsupported_version = EnumOption(
        advanced=True,
        help=lambda cls: textwrap.dedent(
            f"""
                What action to take in case the requested version of {cls.name} is not supported.

                Supported {cls.name} versions: {cls.version_constraints if cls.version_constraints else "unspecified"}
                """
        ),
        default=UnsupportedVersionUsage.RaiseError,
    )

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

    def known_version(self, plat: Platform) -> ExternalToolVersion | None:
        for known_version in self.known_versions:
            tool_version = self.decode_known_version(known_version)
            if plat.value == tool_version.platform and tool_version.version == self.version:
                return tool_version
        return None

    def get_request(self, plat: Platform) -> ExternalToolRequest:
        """Generate a request for this tool."""

        tool_version = self.known_version(plat)
        if tool_version:
            return self.get_request_for(
                tool_version.platform,
                tool_version.sha256,
                tool_version.filesize,
                url_override=tool_version.url_override,
            )
        raise UnknownVersion(
            softwrap(
                f"""
                No known version of {self.name} {self.version} for {plat.value} found in
                {self.known_versions}
                """
            )
        )

    @classmethod
    def decode_known_version(cls, known_version: str) -> ExternalToolVersion:
        try:
            return ExternalToolVersion.decode(known_version)
        except ValueError:
            raise ExternalToolError(
                f"Bad value for [{cls.options_scope}].known_versions: {known_version}"
            )

    @classmethod
    def split_known_version_str(cls, known_version: str) -> tuple[str, str, str, int]:
        version = cls.decode_known_version(known_version)
        return version.version, version.platform, version.sha256, version.filesize

    def get_request_for(
        self, plat_val: str, sha256: str, length: int, url_override: str | None = None
    ) -> ExternalToolRequest:
        """Generate a request for this tool from the given info."""
        plat = Platform(plat_val)
        digest = FileDigest(fingerprint=sha256, serialized_bytes_length=length)
        try:
            url = url_override or self.generate_url(plat)
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
        # packaging.requirements.Requirement's ability to check version constraints.
        constraints = Requirement(f"{self.name}{self.version_constraints}")
        if constraints.specifier.contains(self.version):
            # all ok
            return None

        msg = [
            f"The option [{self.options_scope}].version is set to {self.version}, which is not "
            f"compatible with what this release of Pants expects: {constraints}.",
            "Please update the version to a supported value, or consider using a different Pants",
            "release if you cannot change the version.",
        ]

        if self.use_unsupported_version is UnsupportedVersionUsage.LogWarning:
            msg.extend(
                [
                    "Alternatively, you can ignore this warning (at your own peril) by adding this",
                    "to the GLOBAL section of pants.toml:",
                    f'ignore_warnings = ["The option [{self.options_scope}].version is set to"].',
                ]
            )
            logger.warning(" ".join(msg))
        elif self.use_unsupported_version is UnsupportedVersionUsage.RaiseError:
            msg.append(
                softwrap(
                    f"""
                Alternatively, update [{self.options_scope}].use_unsupported_version to be
                'warning'.
                """
                )
            )
            raise UnsupportedVersion(" ".join(msg))


class TemplatedExternalToolOptionsMixin(ExternalToolOptionsMixin):
    """Common options for implementing a subsystem providing an `ExternalToolRequest` via a URL
    template."""

    default_url_template: str
    default_url_platform_mapping: dict[str, str] | None = None

    url_template = StrOption(
        default=lambda cls: cls.default_url_template,
        advanced=True,
        help=softwrap(
            f"""
            URL to download the tool, either as a single binary file or a compressed file
            (e.g. zip file). You can change this to point to your own hosted file, e.g. to
            work with proxies or for access via the filesystem through a `file:$abspath` URL (e.g.
            `file:/this/is/absolute`, possibly by
            [templating the buildroot in a config file]({doc_url("docs/using-pants/key-concepts/options#config-file-entries")})).

            Use `{{version}}` to have the value from `--version` substituted, and `{{platform}}` to
            have a value from `--url-platform-mapping` substituted in, depending on the
            current platform. For example,
            https://github.com/.../protoc-{{version}}-{{platform}}.zip.
            """
        ),
    )

    url_platform_mapping = DictOption[str](
        "--url-platform-mapping",
        default=lambda cls: cls.default_url_platform_mapping,
        advanced=True,
        help=softwrap(
            """
            A dictionary mapping platforms to strings to be used when generating the URL
            to download the tool.

            In `--url-template`, anytime the `{platform}` string is used, Pants will determine the
            current platform, and substitute `{platform}` with the respective value from your dictionary.

            For example, if you define `{"macos_x86_64": "apple-darwin", "linux_x86_64": "unknown-linux"}`,
            and run Pants on Linux with an intel architecture, then `{platform}` will be substituted
            in the `--url-template` option with `unknown-linux`.
            """
        ),
    )


class TemplatedExternalTool(ExternalTool, TemplatedExternalToolOptionsMixin):
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

    def generate_url(self, plat: Platform) -> str:
        platform = self.url_platform_mapping.get(plat.value, "")
        return self.url_template.format(version=self.version, platform=platform)


@rule(level=LogLevel.DEBUG)
async def download_external_tool(request: ExternalToolRequest) -> DownloadedExternalTool:
    # Download and extract.
    maybe_archive_digest = await download_file(request.download_file_request, **implicitly())
    extracted_archive = await maybe_extract_archive(**implicitly(maybe_archive_digest))
    digest = extracted_archive.digest
    digest_entries = await get_digest_entries(digest)
    if request.strip_common_path_prefix:
        paths = tuple(entry.path for entry in digest_entries)
        if len(paths) == 1:
            commonpath = os.path.dirname(paths[0])
        else:
            commonpath = os.path.commonpath(paths)
            digest = await remove_prefix(RemovePrefix(extracted_archive.digest, commonpath))

    # Confirm executable.
    exe_path = request.exe.lstrip("./")
    is_not_executable = False
    updated_digest_entries = []
    for entry in digest_entries:
        if isinstance(entry, FileEntry) and entry.path == exe_path and not entry.is_executable:
            # We should recreate the digest with the executable bit set.
            is_not_executable = True
            entry = dataclasses.replace(entry, is_executable=True)
        updated_digest_entries.append(entry)
    if is_not_executable:
        digest = await create_digest(CreateDigest(updated_digest_entries))

    return DownloadedExternalTool(digest, request.exe)


@dataclass(frozen=True)
class ExportExternalToolRequest(ExportRequest):
    pass
    # tool: type[ExternalTool]


@dataclass(frozen=True)
class _ExportExternalToolForResolveRequest(EngineAwareParameter):
    resolve: str


@dataclass(frozen=True)
class MaybeExportResult:
    result: ExportResult | None


@rule(level=LogLevel.DEBUG)
async def export_external_tool(
    req: _ExportExternalToolForResolveRequest, platform: Platform, union_membership: UnionMembership
) -> MaybeExportResult:
    """Export a downloadable tool. Downloads all the tools to `bins`, and symlinks the primary exe
    to the `bin` directory.

    We use the last segment of the exe instead of the resolve because:
    - it's probably the exe name people expect
    - avoids clutter from the resolve name (ex "tfsec" instead of "terraform-tfsec")
    """
    exportables = ExportableTool.filter_for_subclasses(
        union_membership,
        ExternalTool,  # type:ignore[type-abstract]  # ExternalTool is abstract, and mypy doesn't like that we might return it
    )
    maybe_exportable = exportables.get(req.resolve)
    if not maybe_exportable:
        return MaybeExportResult(None)

    tool = await _construct_subsystem(maybe_exportable)
    downloaded_tool = await download_external_tool(tool.get_request(platform))

    dest = os.path.join("bins", tool.name)

    exe = tool.generate_exe(platform)
    return MaybeExportResult(
        ExportResult(
            description=f"Export tool {req.resolve}",
            reldir=dest,
            digest=downloaded_tool.digest,
            resolve=req.resolve,
            exported_binaries=(ExportedBinary(name=tool.binary_name, path_in_export=exe),),
        )
    )


@rule
async def export_external_tools(
    request: ExportExternalToolRequest, export: ExportSubsystem
) -> ExportResults:
    maybe_tools = await concurrently(
        export_external_tool(_ExportExternalToolForResolveRequest(resolve), **implicitly())
        for resolve in export.binaries
    )
    return ExportResults(tool.result for tool in maybe_tools if tool.result is not None)


def rules():
    return (
        *collect_rules(),
        *archive.rules(),
        UnionRule(ExportRequest, ExportExternalToolRequest),
    )
