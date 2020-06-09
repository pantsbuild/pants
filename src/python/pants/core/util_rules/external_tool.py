# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import abstractmethod
from dataclasses import dataclass
from pathlib import PurePath
from typing import List

from pants.base.build_environment import get_buildroot
from pants.core.util_rules.archive import ExtractedDigest, MaybeExtractable
from pants.engine.fs import Digest, DirectoryToMaterialize, Snapshot, UrlToFetch
from pants.engine.platform import Platform
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_method
from pants.util.meta import classproperty


class UnknownVersion(Exception):
    pass


class ExternalToolError(Exception):
    pass


@dataclass(frozen=True)
class ExternalToolRequest:
    url_to_fetch: UrlToFetch
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

        @classmethod
        def generate_url(cls, plat: Platform, version: str) -> str:
            ...

        @classmethod
        def generate_exe(cls, plat: Platform, version: str) -> str:
            ...

    @rule
    def my_rule(my_external_tool: MyExternalTool):
      downloaded_tool = await Get[DownloadedExternalTool](
        ExternalToolRequest, my_external_tool.get_request(Platform.current)
      )

    ...
    def rules():
      return [my_rule, SubsystemRule(MyExternalTool)]


    A lightweight replacement for the code in binary_tool.py and binary_util.py,
    which can be deprecated in favor of this.
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
            fingerprint=True,
            help=f"Use this version of {cls.name}.",
        )
        register(
            "--known-versions",
            type=list,
            member_type=str,
            default=cls.default_known_versions,
            advanced=True,
            help=f"Known versions to verify downloads against. Each element is a "
            f"pipe-separated string of version|platform|sha256|length, where `version` is the "
            f"version string, `platform` is one of [{','.join(Platform.__members__.keys())}], "
            f"`sha256` is the 64-character hex representation of the expected sha256 digest of the "
            f"download file, as emitted by `shasum -a 256`, and `length` is the expected length of "
            f"the download file in bytes. E.g., '3.1.2|darwin|"
            f"6d0f18cd84b918c7b3edd0203e75569e0c7caecb1367bbbe409b44e28514f5be|42813'. "
            f"Values are space-stripped, so pipes can be indented for readability if necessary."
            f"You can compute the length and sha256 easily with:  "
            f"curl -L $URL | tee >(wc -c) >(shasum -a 256) >/dev/null",
        )

    @abstractmethod
    def generate_url(self, plat: Platform) -> str:
        """Returns the URL for the given version of the tool, runnable on the given os+arch.

        os and arch default to those of the current system.

        Implementations should raise ExternalToolError if they cannot resolve the arguments
        to a URL.  The raised exception need not have a message - a sensible one will be generated.
        """

    def generate_exe(self, plat: Platform) -> str:
        """Returns the archive path to the given version of the tool.

        If the tool is downloaded directly, not in an archive, this can be left unimplemented.
        """
        return ""

    def get_request(self, plat: Platform) -> ExternalToolRequest:
        """Generate a request for this tool."""
        version = self.get_options().version
        known_versions = self.get_options().known_versions
        for known_version in known_versions:
            try:
                ver, plat_val, sha256, length = (x.strip() for x in known_version.split("|"))
            except ValueError:
                raise ExternalToolError(
                    f"Bad value for --known-versions (see ./pants "
                    f"help-advanced {self.options_scope}): {known_version}"
                )
            if plat_val == plat.value and ver == version:
                digest = Digest(fingerprint=sha256, serialized_bytes_length=int(length))
                try:
                    url = self.generate_url(plat)
                    exe = self.generate_exe(plat) or url.rsplit("/", 1)[-1]
                except ExternalToolError as e:
                    raise ExternalToolError(
                        f"Couldn't find {self.name} version {version} on {plat.value}"
                    ) from e
                return ExternalToolRequest(UrlToFetch(url=url, digest=digest), exe)
        raise UnknownVersion(
            f"No known version of {self.name} {version} for {plat.value} found in {known_versions}"
        )

    @memoized_method
    def select(self, context=None):
        """For backwards compatibility with v1 code.

        Can be removed once all v1 callers are gone.
        """
        req = self.get_request(Platform.current)
        rel_workdir = PurePath(context.options.for_global_scope().pants_workdir).relative_to(
            get_buildroot()
        )
        rel_bindir = (
            rel_workdir / "external_tools" / self.name / req.url_to_fetch.digest.fingerprint
        )

        downloaded_external_tool = context._scheduler.product_request(
            DownloadedExternalTool, [self.get_request(Platform.current)]
        )[0]
        context._scheduler.materialize_directory(
            DirectoryToMaterialize(
                downloaded_external_tool.digest, path_prefix=rel_bindir.as_posix()
            )
        )
        return (PurePath(get_buildroot()) / rel_bindir / req.exe).as_posix()


@rule
async def download_external_tool(request: ExternalToolRequest) -> DownloadedExternalTool:
    snapshot = await Get[Snapshot](UrlToFetch, request.url_to_fetch)
    extracted_digest = await Get[ExtractedDigest](MaybeExtractable(snapshot.digest))
    return DownloadedExternalTool(extracted_digest.digest, request.exe)


def rules():
    return [download_external_tool, RootRule(ExternalToolRequest)]
