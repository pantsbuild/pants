# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union, cast

from pants.binaries.binary_util import (
    BinaryRequest,
    BinaryToolUrlGenerator,
    BinaryUtil,
    HostPlatform,
)
from pants.engine.fs import Digest, PathGlobs, PathGlobsAndRoot, Snapshot, UrlToFetch
from pants.engine.platform import Platform, PlatformConstraint
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get
from pants.fs.archive import XZCompressedTarArchiver, create_archiver
from pants.subsystem.subsystem import Subsystem
from pants.util.enums import match
from pants.util.memo import memoized_method, memoized_property
from pants.util.meta import frozen_after_init
from pants.util.osutil import get_closest_mac_host_platform_pair

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolVersion:
    version: str


@dataclass(frozen=True)
class ToolForPlatform:
    version: ToolVersion
    digest: Digest

    def into_tuple(self) -> Tuple[str, str, int]:
        return (self.version.version, self.digest.fingerprint, self.digest.serialized_bytes_length)


@rule
def translate_host_platform(
    platform_constraint: PlatformConstraint, binary_util: BinaryUtil,
) -> HostPlatform:
    # This method attempts to provide a uname function to BinaryUtil.host_platform() so that the
    # download urls can be calculated. For platforms that are different than the current host, we try
    # to "spoof" the most appropriate value.
    if Platform.current == Platform.darwin:
        darwin_uname: Any = os.uname
        linux_uname: Any = lambda: ("linux", None, None, None, "x86_64")
    else:
        assert Platform.current == Platform.linux
        darwin_uname = lambda: (
            "darwin",
            None,
            get_closest_mac_host_platform_pair(),
            None,
            "x86_64",
        )
        linux_uname = os.uname

    return cast(
        HostPlatform,
        match(
            platform_constraint,
            {
                PlatformConstraint.none: lambda: HostPlatform.empty,
                PlatformConstraint.darwin: lambda: binary_util.host_platform(uname=darwin_uname()),
                PlatformConstraint.linux: lambda: binary_util.host_platform(uname=linux_uname()),
            },
        )(),
    )


# TODO: Add integration tests for this file.
class BinaryToolBase(Subsystem):
    """Base class for subsytems that configure binary tools.

    Subclasses can be further subclassed, manually, e.g., to add any extra options.

    :API: public
    """

    # Subclasses must set these to appropriate values for the tool they define.
    # They must also set options_scope appropriately.
    platform_dependent: Optional[bool] = None
    archive_type: Optional[str] = None  # See pants.fs.archive.archive for valid string values.

    default_version: Optional[str] = None
    default_versions_and_digests: Dict[PlatformConstraint, ToolForPlatform] = {}

    # Subclasses may set this to the tool name as understood by BinaryUtil.
    # If unset, it defaults to the value of options_scope.
    name: Optional[str] = None

    # Subclasses may set this to a suffix (e.g., '.pex') to add to the computed remote path.
    # Note that setting archive_type will add an appropriate archive suffix after this suffix.
    suffix = ""

    # Subclasses may set these to effect migration from an old --version option to this one.
    # TODO(benjy): Remove these after migration to the mixin is complete.
    replaces_scope: Optional[str] = None
    replaces_name: Optional[str] = None

    # Subclasses may set this to provide extra register() kwargs for the --version option.
    extra_version_option_kwargs = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._snapshot_lock = threading.Lock()

    @classmethod
    def subsystem_dependencies(cls):
        sub_deps = super().subsystem_dependencies() + (BinaryUtil.Factory,)

        # TODO: if we need to do more conditional subsystem dependencies, do it declaratively with a
        # dict class field so that we only try to create or access it if we declared a dependency on it.
        if cls.archive_type == "txz":
            sub_deps = sub_deps + (XZ.scoped(cls),)

        return sub_deps

    @memoized_property
    def _xz(self):
        if self.archive_type == "txz":
            return XZ.scoped_instance(self)
        return None

    @memoized_method
    def _get_archiver(self):
        if not self.archive_type:
            return None

        # This forces downloading and extracting the `XZ` archive if any BinaryTool with a 'txz'
        # archive_type is used, but that's fine, because unless the cache is manually changed we won't
        # do more work than necessary.
        if self.archive_type == "txz":
            return self._xz.tar_xz_extractor

        return create_archiver(self.archive_type)

    def get_external_url_generator(self):
        """Override and return an instance of BinaryToolUrlGenerator to download from those urls.

        If this method returns None, urls to download the tool will be constructed from
        --binaries-baseurls. Otherwise, generate_urls() will be invoked on the result with the requested
        version and host platform.

        If the bootstrap option --allow-external-binary-tool-downloads is False, the result of this
        method will be ignored. Implementations of BinaryTool must be aware of differences (e.g., in
        archive structure) between the external and internal versions of the downloaded tool, if any.

        See the :class:`LLVM` subsystem for an example of usage.
        """
        return None

    @classmethod
    def register_options(cls, register):
        super().register_options(register)

        version_registration_kwargs = {
            "type": str,
            "default": cls.default_version,
        }
        if cls.extra_version_option_kwargs:
            version_registration_kwargs.update(cls.extra_version_option_kwargs)
        version_registration_kwargs["help"] = version_registration_kwargs.get(
            "help"
        ) or "Version of the {} {} to use".format(
            cls._get_name(), "binary" if cls.platform_dependent else "script"
        )
        # The default for fingerprint in register() is False, but we want to default to True.
        if "fingerprint" not in version_registration_kwargs:
            version_registration_kwargs["fingerprint"] = True
        register("--version", **version_registration_kwargs)

        register(
            "--version-digest-mapping",
            type=dict,
            default={
                # "Serialize" the default value dict into "basic" types that can be easily specified
                # in pants.toml.
                platform_constraint.value: tool.into_tuple()
                for platform_constraint, tool in cls.default_versions_and_digests.items()
            },
            fingerprint=True,
            help="A dict mapping <platform constraint> -> (<version>, <fingerprint>, <size_bytes>)."
            f'A "platform constraint" is any of {[c.value for c in PlatformConstraint]}, and '
            "is the platform to fetch the tool for. A platform-independent tool should "
            f"use {PlatformConstraint.none.value}, while a platform-dependent tool should specify "
            'all environments it needs to be used for. The "fingerprint" and "size_bytes" '
            "arguments are the result printed when running `sha256sum` and `wc -c` on "
            "the downloaded file, respectively.",
        )

    @memoized_method
    def select(self, context=None):
        """Returns the path to the specified binary tool.

        If replaces_scope and replaces_name are defined, then the caller must pass in
        a context, otherwise no context should be passed.

        # TODO: Once we're migrated, get rid of the context arg.

        :API: public
        """
        return self._select_for_version(self.version(context))

    @memoized_method
    def version(self, context=None):
        """Returns the version of the specified binary tool.

        If replaces_scope and replaces_name are defined, then the caller must pass in
        a context, otherwise no context should be passed.

        # TODO: Once we're migrated, get rid of the context arg.

        :API: public
        """
        if self.replaces_scope and self.replaces_name:
            if context:
                # If the old option is provided explicitly, let it take precedence.
                old_opts = context.options.for_scope(self.replaces_scope)
                if old_opts.get(self.replaces_name) and not old_opts.is_default(self.replaces_name):
                    return old_opts.get(self.replaces_name)
            else:
                logger.warning(
                    "Cannot resolve version of {} from deprecated option {} in scope {} without a "
                    "context!".format(self._get_name(), self.replaces_name, self.replaces_scope)
                )
        return self.get_options().version

    @memoized_property
    def _binary_util(self):
        return BinaryUtil.Factory.create()

    @classmethod
    def _get_name(cls):
        return cls.name or cls.options_scope

    @classmethod
    def get_support_dir(cls):
        return "bin/{}".format(cls._get_name())

    @classmethod
    def _name_to_fetch(cls):
        return "{}{}".format(cls._get_name(), cls.suffix)

    def make_binary_request(self, version):
        return BinaryRequest(
            supportdir=self.get_support_dir(),
            version=version,
            name=self._name_to_fetch(),
            platform_dependent=self.platform_dependent,
            external_url_generator=self.get_external_url_generator(),
            archiver=self._get_archiver(),
        )

    def _select_for_version(self, version):
        binary_request = self.make_binary_request(version)
        return self._binary_util.select(binary_request)

    @memoized_method
    def _hackily_snapshot_exclusive(self, context):
        bootstrapdir = self.get_options().pants_bootstrapdir
        relpath = os.path.relpath(self.select(context), bootstrapdir)
        snapshot = context._scheduler.capture_snapshots(
            (PathGlobsAndRoot(PathGlobs((relpath,)), bootstrapdir,),)
        )[0]
        return (relpath, snapshot)

    def hackily_snapshot(self, context):
        """Returns a Snapshot of this tool after downloading it.

        TODO: See https://github.com/pantsbuild/pants/issues/7790, which would make this unnecessary
        due to the engine's memoization and caching.
        """
        # We call a memoized method under a lock in order to avoid doing a bunch of redundant
        # fetching and snapshotting.
        with self._snapshot_lock:
            return self._hackily_snapshot_exclusive(context)


class NativeTool(BinaryToolBase):
    """A base class for native-code tools.

    :API: public
    """

    platform_dependent = True


class Script(BinaryToolBase):
    """A base class for platform-independent scripts.

    :API: public
    """

    platform_dependent = False


class XZ(NativeTool):
    options_scope = "xz"
    default_version = "5.2.4-3"
    archive_type = "tgz"

    @memoized_property
    def tar_xz_extractor(self):
        return XZCompressedTarArchiver(self._executable_location())

    def _executable_location(self):
        return os.path.join(self.select(), "bin", "xz")


@frozen_after_init
@dataclass(unsafe_hash=True)
class VersionDigestMapping:
    """Parse the --version-digest-mapping option back into a dictionary."""

    version_digest_mapping: Tuple[Tuple[str, Tuple[str, str, int]], ...]

    def __init__(self, version_digest_mapping: Dict[str, List[Union[str, int]]]) -> None:
        self.version_digest_mapping = tuple(
            (platform_constraint, tuple(data))  # type: ignore[misc]
            for platform_constraint, data in version_digest_mapping.items()
        )

    @memoized_property
    def _deserialized_mapping(self,) -> Dict[PlatformConstraint, ToolForPlatform]:
        deserialized: Dict[PlatformConstraint, ToolForPlatform] = {}
        for platform_constraint, (version, fingerprint, size_bytes) in self.version_digest_mapping:
            deserialized[PlatformConstraint(platform_constraint)] = ToolForPlatform(
                version=ToolVersion(version), digest=Digest(fingerprint, size_bytes),
            )
        return deserialized

    def get(self, platform_constraint: PlatformConstraint) -> ToolForPlatform:
        return self._deserialized_mapping[platform_constraint]


@dataclass(frozen=True)
class BinaryToolUrlSet:
    tool_for_platform: ToolForPlatform
    host_platform: HostPlatform
    url_generator: BinaryToolUrlGenerator

    def get_urls(self) -> List[str]:
        return self.url_generator.generate_urls(
            version=self.tool_for_platform.version.version,
            host_platform=self.host_platform if self.host_platform != HostPlatform.empty else None,
        )


@frozen_after_init
@dataclass(unsafe_hash=True)
class BinaryToolFetchRequest:
    tool: BinaryToolBase
    platform_constraint: PlatformConstraint

    def __init__(
        self, tool: BinaryToolBase, platform_constraint: Optional[PlatformConstraint] = None,
    ) -> None:
        self.tool = tool
        if platform_constraint is None:
            if tool.platform_dependent:
                platform_constraint = PlatformConstraint.local_platform
            else:
                platform_constraint = PlatformConstraint.none

        self.platform_constraint = platform_constraint


@rule
async def get_binary_tool_urls(
    req: BinaryToolFetchRequest, binary_util: BinaryUtil,
) -> BinaryToolUrlSet:
    tool = req.tool
    platform_constraint = req.platform_constraint

    mapping = VersionDigestMapping(tool.get_options().version_digest_mapping)
    tool_for_platform = mapping.get(platform_constraint)

    version = tool_for_platform.version.version
    url_generator = binary_util.get_url_generator(tool.make_binary_request(version))

    host_platform = await Get[HostPlatform](PlatformConstraint, platform_constraint)

    return BinaryToolUrlSet(
        tool_for_platform=tool_for_platform,
        host_platform=host_platform,
        url_generator=url_generator,
    )


@rule
async def fetch_binary_tool(req: BinaryToolFetchRequest, url_set: BinaryToolUrlSet) -> Snapshot:
    digest = url_set.tool_for_platform.digest
    urls = url_set.get_urls()

    if not urls:
        raise ValueError(
            f"binary tool url generator {url_set.url_generator} produced an empty list of "
            f"urls for the request {req}"
        )
    # TODO: allow fetching a UrlToFetch with failure! Consider FallibleUrlToFetch analog to
    # FallibleProcessResult!
    url_to_fetch = urls[0]

    return await Get[Snapshot](UrlToFetch(url_to_fetch, digest))


def rules():
    return [
        RootRule(PlatformConstraint),
        translate_host_platform,
        get_binary_tool_urls,
        fetch_binary_tool,
        RootRule(BinaryToolFetchRequest),
    ]
