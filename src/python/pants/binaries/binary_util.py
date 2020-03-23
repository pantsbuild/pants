# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import argparse
import logging
import os
import posixpath
import shutil
import sys
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from functools import reduce
from typing import Any, List, Optional, Tuple, cast

from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.engine.rules import rule
from pants.fs.archive import archiver_for_path
from pants.net.http.fetcher import Fetcher
from pants.option.global_options import GlobalOptions
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.subsystem.subsystem import Subsystem
from pants.util.contextutil import temporary_file
from pants.util.dirutil import chmod_plus_x, safe_concurrent_creation, safe_open
from pants.util.memo import memoized_classproperty, memoized_method, memoized_property
from pants.util.ordered_set import OrderedSet
from pants.util.osutil import (
    SUPPORTED_PLATFORM_NORMALIZED_NAMES,
    get_closest_mac_host_platform_pair,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HostPlatform:
    """Describes a platform to resolve binaries for. Determines the binary's location on disk.

    :class:`BinaryToolUrlGenerator` instances receive this to generate download urls.
    """

    os_name: Optional[str]
    arch_or_version: Optional[str]

    @memoized_classproperty
    def empty(cls):
        return cls(None, None)

    def binary_path_components(self):
        """These strings are used as consecutive components of the path where a binary is fetched.

        This is also used in generating urls from --binaries-baseurls in PantsHosted.
        """
        return [self.os_name, self.arch_or_version]


class BinaryToolUrlGenerator(ABC):
    """Encapsulates the selection of urls to download for some binary tool.

    :API: public

    :class:`BinaryTool` subclasses can return an instance of a class mixing this in to
    get_external_url_generator(self) to download their file or archive from some specified url or set
    of urls.
    """

    @abstractmethod
    def generate_urls(self, version, host_platform) -> List[str]:
        """Return a list of urls to download some binary tool from given a version and platform.

        Each url is tried in order to resolve the binary -- if the list of urls is empty, or downloading
        from each of the urls fails, Pants will raise an exception when the binary tool is fetched which
        should describe why the urls failed to work.

        :param str version: version string for the requested binary (e.g. '2.0.1').
        :param host_platform: description of the platform to fetch binaries for.
        :type host_platform: :class:`HostPlatform`
        :returns: a list of urls to download the binary tool from.
        :rtype: list
        """
        pass


class PantsHosted(BinaryToolUrlGenerator):
    """Given a binary request and --binaries-baseurls, generate urls to download the binary from.

    This url generator is used if get_external_url_generator(self) is not overridden by a BinaryTool
    subclass, or if --allow-external-binary-tool-downloads is False.

    NB: "pants-hosted" is referring to the organization of the urls being specific to pants. It also
    happens that most binaries are downloaded from S3 hosting at binaries.pantsbuild.org by default --
    but setting --binaries-baseurls to anything else will only download binaries from the baseurls
    given, not from binaries.pantsbuild.org.
    """

    class NoBaseUrlsError(ValueError):
        pass

    def __init__(self, binary_request, baseurls):
        super().__init__()
        self._binary_request = binary_request

        if not baseurls:
            raise self.NoBaseUrlsError(
                "Error constructing pants-hosted urls for the {} binary: no baseurls were provided.".format(
                    binary_request.name
                )
            )
        self._baseurls = baseurls

    def generate_urls(self, version, host_platform):
        """Append the file's download path to each of --binaries-baseurls.

        This assumes that the urls in --binaries-baseurls point somewhere that mirrors Pants's
        organization of the downloaded binaries on disk. Each url is tried in order until a request
        succeeds.
        """
        binary_path = self._binary_request.get_download_path(host_platform)
        return [posixpath.join(baseurl, binary_path) for baseurl in self._baseurls]


# TODO: Deprecate passing in an explicit supportdir? Seems like we should be able to
# organize our binary hosting so that it's not needed. It's also used to calculate the binary
# download location, though.
@dataclass(frozen=True)
class BinaryRequest:
    """Describes a request for a binary to download."""

    supportdir: Any
    version: Any
    name: Any
    platform_dependent: Any
    external_url_generator: Optional[Any]
    archiver: Optional[Any]

    def _full_name(self):
        if self.archiver:
            return "{}.{}".format(self.name, self.archiver.extension)
        return self.name

    def get_download_path(self, host_platform):
        binary_path_components = [self.supportdir]
        if self.platform_dependent:
            # TODO(John Sirois): finish doc of the path structure expected under base_path.
            binary_path_components.extend(host_platform.binary_path_components())
        binary_path_components.extend([self.version, self._full_name()])
        return os.path.join(*binary_path_components)


@dataclass(frozen=True)
class BinaryFetchRequest:
    """Describes a request to download a file."""

    download_path: Any
    urls: Tuple

    def __post_init__(self):
        if not self.urls:
            raise self.NoDownloadUrlsError(f"No urls were provided to {self.__name__}: {self!r}.")

    @memoized_property
    def file_name(self):
        return os.path.basename(self.download_path)

    class NoDownloadUrlsError(ValueError):
        pass


class BinaryToolFetcher:
    @classmethod
    def _default_http_fetcher(cls):
        """Return a fetcher that resolves local file paths against the build root.

        Currently this is used everywhere except in testing.
        """
        return Fetcher(get_buildroot())

    def __init__(self, bootstrap_dir, timeout_secs, fetcher=None, ignore_cached_download=False):
        """
        :param str bootstrap_dir: The root directory where Pants downloads binaries to.
        :param int timeout_secs: The number of seconds to wait before timing out on a request for some
                                 url.
        :param fetcher: object to fetch urls with, overridden in testing.
        :type fetcher: :class:`pants.net.http.fetcher.Fetcher`
        :param bool ignore_cached_download: whether to fetch a binary even if it already exists on disk.
        """
        self._bootstrap_dir = bootstrap_dir
        self._timeout_secs = timeout_secs
        self._fetcher = fetcher or self._default_http_fetcher()
        self._ignore_cached_download = ignore_cached_download

    class BinaryNotFound(TaskError):
        def __init__(self, name, accumulated_errors):
            super(BinaryToolFetcher.BinaryNotFound, self).__init__(
                "Failed to fetch {name} binary from any source: ({error_msgs})".format(
                    name=name, error_msgs=", ".join(accumulated_errors)
                )
            )

    @contextmanager
    def _select_binary_stream(self, name, urls):
        """Download a file from a list of urls, yielding a stream after downloading the file.

        URLs are tried in order until they succeed.

        :raises: :class:`BinaryToolFetcher.BinaryNotFound` if requests to all the given urls fail.
        """
        downloaded_successfully = False
        accumulated_errors = []
        for url in OrderedSet(urls):  # De-dup URLS: we only want to try each URL once.
            logger.info(
                "Attempting to fetch {name} binary from: {url} ...".format(name=name, url=url)
            )
            try:
                with temporary_file() as dest:
                    logger.debug(
                        "in BinaryToolFetcher: url={}, timeout_secs={}".format(
                            url, self._timeout_secs
                        )
                    )
                    self._fetcher.download(
                        url,
                        listener=Fetcher.ProgressListener(),
                        path_or_fd=dest,
                        timeout_secs=self._timeout_secs,
                    )
                    logger.info("Fetched {name} binary from: {url} .".format(name=name, url=url))
                    downloaded_successfully = True
                    dest.seek(0)
                    yield dest
                    break
            except (IOError, Fetcher.Error, ValueError) as e:
                accumulated_errors.append(
                    "Failed to fetch binary from {url}: {error}".format(url=url, error=e)
                )
        if not downloaded_successfully:
            raise self.BinaryNotFound(name, accumulated_errors)

    def _do_fetch(self, download_path, file_name, urls):
        with safe_concurrent_creation(download_path) as downloadpath:
            with self._select_binary_stream(file_name, urls) as binary_tool_stream:
                with safe_open(downloadpath, "wb") as bootstrapped_binary:
                    shutil.copyfileobj(binary_tool_stream, bootstrapped_binary)

    def fetch_binary(self, fetch_request):
        """Fulfill a binary fetch request."""
        bootstrap_dir = os.path.realpath(os.path.expanduser(self._bootstrap_dir))
        bootstrapped_binary_path = os.path.join(bootstrap_dir, fetch_request.download_path)
        logger.debug("bootstrapped_binary_path: {}".format(bootstrapped_binary_path))
        file_name = fetch_request.file_name
        urls = fetch_request.urls

        if self._ignore_cached_download or not os.path.exists(bootstrapped_binary_path):
            self._do_fetch(bootstrapped_binary_path, file_name, urls)

        logger.debug(
            "Selected {binary} binary bootstrapped to: {path}".format(
                binary=file_name, path=bootstrapped_binary_path
            )
        )
        return bootstrapped_binary_path


class BinaryUtil:
    """Wraps utility methods for finding binary executables."""

    class Factory(Subsystem):
        """
        :API: public
        """

        # N.B. `BinaryUtil` sources all of its options from bootstrap options, so that
        # `BinaryUtil` instances can be created prior to `Subsystem` bootstrapping. So
        # this options scope is unused, but required to remain a `Subsystem`.
        options_scope = "binaries"

        @classmethod
        def create(cls) -> "BinaryUtil":
            # NB: create is a class method to ~force binary fetch location to be global.
            return cast(BinaryUtil, cls._create_for_cls(BinaryUtil))

        @classmethod
        def _create_for_cls(cls, binary_util_cls):
            # NB: We read global bootstrap options, but through our own scoped options instance.
            options = cls.global_instance().get_options()
            binary_tool_fetcher = BinaryToolFetcher(
                bootstrap_dir=options.pants_bootstrapdir,
                timeout_secs=options.binaries_fetch_timeout_secs,
            )
            return binary_util_cls(
                baseurls=options.binaries_baseurls,
                binary_tool_fetcher=binary_tool_fetcher,
                path_by_id=options.binaries_path_by_id,
                allow_external_binary_tool_downloads=options.allow_external_binary_tool_downloads,
            )

    class MissingMachineInfo(TaskError):
        """Indicates that pants was unable to map this machine's OS to a binary path prefix."""

        pass

    class NoBaseUrlsError(TaskError):
        """Indicates that no URLs were specified in pants.toml."""

        pass

    class BinaryResolutionError(TaskError):
        """Raised to wrap other exceptions raised in the select() method to provide context."""

        def __init__(self, binary_request, base_exception):
            super(BinaryUtil.BinaryResolutionError, self).__init__(
                "Error resolving binary request {}: {}".format(binary_request, base_exception),
                base_exception,
            )

    def __init__(
        self,
        baseurls,
        binary_tool_fetcher,
        path_by_id=None,
        allow_external_binary_tool_downloads=True,
        uname_func=None,
    ):
        """Creates a BinaryUtil with the given settings to define binary lookup behavior.

        This constructor is primarily used for testing.  Production code will usually initialize
        an instance using the BinaryUtil.Factory.create() method.

        :param baseurls: URL prefixes which represent repositories of binaries.
        :type baseurls: list of string
        :param int timeout_secs: Timeout in seconds for url reads.
        :param string bootstrapdir: Directory to use for caching binaries.  Uses this directory to
          search for binaries in, or download binaries to if needed.
        :param dict path_by_id: Additional mapping from (sysname, id) -> (os, arch) for tool
          directory naming
        :param bool allow_external_binary_tool_downloads: If False, use --binaries-baseurls to download
                                                          all binaries, regardless of whether an
                                                          external_url_generator field is provided.
        :param function uname_func: method to use to emulate os.uname() in testing
        """
        self._baseurls = baseurls
        self._binary_tool_fetcher = binary_tool_fetcher

        self._path_by_id = SUPPORTED_PLATFORM_NORMALIZED_NAMES.copy()
        if path_by_id:
            self._path_by_id.update((tuple(k), tuple(v)) for k, v in path_by_id.items())

        self._allow_external_binary_tool_downloads = allow_external_binary_tool_downloads
        self._uname_func = uname_func or os.uname

    _ID_BY_OS = {
        "darwin": lambda release, machine: ("darwin", release.split(".")[0]),
        "linux": lambda release, machine: ("linux", machine),
    }

    # TODO: we create a HostPlatform in this class instead of in the constructor because we don't want
    # to fail until a binary is requested. The HostPlatform should be a parameter that gets lazily
    # resolved by the v2 engine.
    @memoized_method
    def host_platform(self, uname=None):
        uname_result = uname if uname else self._uname_func()
        sysname, _, release, _, machine = uname_result
        os_id_key = sysname.lower()
        try:
            os_id_fun = self._ID_BY_OS[os_id_key]
            os_id_tuple = os_id_fun(release, machine)
        except KeyError:
            # TODO: test this!
            raise self.MissingMachineInfo(
                "Pants could not resolve binaries for the current host: platform '{}' was not recognized. "
                "Recognized platforms are: [{}].".format(
                    os_id_key, ", ".join(sorted(self._ID_BY_OS.keys()))
                )
            )
        try:
            os_name, arch_or_version = self._path_by_id[os_id_tuple]
            return HostPlatform(os_name, arch_or_version)
        except KeyError:
            # In the case of MacOS, arch_or_version represents a version, and newer releases
            # can run binaries built for older releases.
            # It's better to allow that as a fallback, than for Pants to be broken on each new version
            # of MacOS until we get around to adding binaries for that new version, and modifying config
            # appropriately.
            # If some future version of MacOS cannot run binaries built for a previous
            # release, then we're no worse off than we were before (except that the error will be
            # less obvious), and we can fix it by pushing appropriate binaries and modifying
            # SUPPORTED_PLATFORM_NORMALIZED_NAMES appropriately.  This is only likely to happen with a
            # major architecture change, so we'll have plenty of warning.
            if os_id_tuple[0] == "darwin":
                os_name, version = get_closest_mac_host_platform_pair(os_id_tuple[1])
                if os_name is not None and version is not None:
                    return HostPlatform(os_name, version)
            # We fail early here because we need the host_platform to identify where to download
            # binaries to.
            raise self.MissingMachineInfo(
                "Pants could not resolve binaries for the current host. Update --binaries-path-by-id to "
                "find binaries for the current host platform {}.\n"
                "--binaries-path-by-id was: {}.".format(os_id_tuple, self._path_by_id)
            )

    def _get_download_path(self, binary_request):
        return binary_request.get_download_path(self.host_platform())

    def get_url_generator(self, binary_request):

        external_url_generator = binary_request.external_url_generator

        logger.debug(
            "self._allow_external_binary_tool_downloads: {}".format(
                self._allow_external_binary_tool_downloads
            )
        )
        logger.debug("external_url_generator: {}".format(external_url_generator))

        if external_url_generator and self._allow_external_binary_tool_downloads:
            url_generator = external_url_generator
        else:
            if not self._baseurls:
                raise self.NoBaseUrlsError("--binaries-baseurls is empty.")
            url_generator = PantsHosted(binary_request=binary_request, baseurls=self._baseurls)

        return url_generator

    def _get_urls(self, url_generator, binary_request):
        return url_generator.generate_urls(binary_request.version, self.host_platform())

    def select(self, binary_request):
        """Fetches a file, unpacking it if necessary."""

        logger.debug("binary_request: {!r}".format(binary_request))

        try:
            download_path = self._get_download_path(binary_request)
        except self.MissingMachineInfo as e:
            raise self.BinaryResolutionError(binary_request, e)

        try:
            url_generator = self.get_url_generator(binary_request)
        except self.NoBaseUrlsError as e:
            raise self.BinaryResolutionError(binary_request, e)

        urls = self._get_urls(url_generator, binary_request)
        if not isinstance(urls, list):
            # TODO: add test for this error!
            raise self.BinaryResolutionError(
                binary_request, TypeError("urls must be a list: was '{}'.".format(urls))
            )
        fetch_request = BinaryFetchRequest(download_path=download_path, urls=tuple(urls))

        logger.debug("fetch_request: {!r}".format(fetch_request))

        try:
            downloaded_file = self._binary_tool_fetcher.fetch_binary(fetch_request)
        except BinaryToolFetcher.BinaryNotFound as e:
            raise self.BinaryResolutionError(binary_request, e)

        # NB: we mark the downloaded file executable if it is not an archive.
        archiver = binary_request.archiver
        if archiver is None:
            chmod_plus_x(downloaded_file)
            return downloaded_file

        download_dir = os.path.dirname(downloaded_file)
        # Use the 'name' given in the request as the directory name to extract to.
        unpacked_dirname = os.path.join(download_dir, binary_request.name)
        if not os.path.isdir(unpacked_dirname):
            logger.info("Extracting {} to {} .".format(downloaded_file, unpacked_dirname))
            archiver.extract(downloaded_file, unpacked_dirname, concurrency_safe=True)
        return unpacked_dirname

    def _make_deprecated_binary_request(self, supportdir, version, name):
        return BinaryRequest(
            supportdir=supportdir,
            version=version,
            name=name,
            platform_dependent=True,
            external_url_generator=None,
            archiver=None,
        )

    def select_binary(self, supportdir, version, name):
        binary_request = self._make_deprecated_binary_request(supportdir, version, name)
        return self.select(binary_request)

    def _make_deprecated_script_request(self, supportdir, version, name):
        return BinaryRequest(
            supportdir=supportdir,
            version=version,
            name=name,
            platform_dependent=False,
            external_url_generator=None,
            archiver=None,
        )

    def select_script(self, supportdir, version, name):
        binary_request = self._make_deprecated_script_request(supportdir, version, name)
        return self.select(binary_request)


def _create_bootstrap_binary_arg_parser():
    parser = argparse.ArgumentParser(
        description="""\
Helper for download_binary.sh to use BinaryUtil to download the appropriate binaries.

Downloads the specified binary at the specified version if it's not already present.

Outputs an absolute path to the binary, whether fetched or already present, to stdout.

If the file ends in ".tar.gz", untars the file and outputs the directory to which the files were
untar'd. Otherwise, makes the file executable.

If a binary tool with the requested name, version, and filename does not exist, the
script will exit with an error and print a message to stderr.

See binary_util.py for more information.
"""
    )
    parser.add_argument(
        "util_name", help="Subdirectory for the requested tool in the pants hosted binary schema."
    )
    parser.add_argument("version", help="Version of the requested binary tool to download.")
    parser.add_argument(
        "filename",
        nargs="?",
        default=None,
        help="Filename to download. Defaults to the value provided for `util_name`.",
    )
    return parser


def select(argv):
    # Parse positional arguments to the script.
    args = _create_bootstrap_binary_arg_parser().parse_args(argv[1:])
    # Resolve bootstrap options with a fake empty command line.
    options_bootstrapper = OptionsBootstrapper.create(args=[argv[0]])
    subsystems = (GlobalOptions, BinaryUtil.Factory)
    known_scope_infos = reduce(set.union, (ss.known_scope_infos() for ss in subsystems), set())
    options = options_bootstrapper.get_full_options(known_scope_infos)
    # Initialize Subsystems.
    Subsystem.set_options(options)

    # If the filename provided ends in a known archive extension (such as ".tar.gz"), then we get the
    # appropriate Archiver to pass to BinaryUtil.
    archiver_for_current_binary = None
    filename = args.filename or args.util_name
    try:
        archiver_for_current_binary = archiver_for_path(filename)
        # BinaryRequest requires the `name` field to be provided without an extension, as it appends the
        # archiver's extension if one is provided, so we have to remove it here.
        filename = filename[: -(len(archiver_for_current_binary.extension) + 1)]
    except ValueError:
        pass

    binary_util = BinaryUtil.Factory.create()
    binary_request = BinaryRequest(
        supportdir="bin/{}".format(args.util_name),
        version=args.version,
        name=filename,
        platform_dependent=True,
        external_url_generator=None,
        archiver=archiver_for_current_binary,
    )

    return binary_util.select(binary_request)


if __name__ == "__main__":
    print(select(sys.argv))


@rule
def provide_binary_util() -> BinaryUtil:
    return BinaryUtil.Factory.create()


def rules():
    return [
        provide_binary_util,
    ]
