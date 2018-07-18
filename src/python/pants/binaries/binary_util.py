# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import os
import posixpath
import shutil
from abc import abstractmethod
from builtins import object
from contextlib import contextmanager

from twitter.common.collections import OrderedSet

from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.net.http.fetcher import Fetcher
from pants.subsystem.subsystem import Subsystem
from pants.util.contextutil import temporary_file
from pants.util.dirutil import chmod_plus_x, safe_concurrent_creation, safe_open
from pants.util.memo import memoized_method, memoized_property
from pants.util.objects import datatype
from pants.util.osutil import SUPPORTED_PLATFORM_NORMALIZED_NAMES


logger = logging.getLogger(__name__)


class HostPlatform(datatype(['os_name', 'arch_or_version'])):
  """Describes a platform to resolve binaries for. Determines the binary's location on disk.

  :class:`BinaryToolUrlGenerator` instances receive this to generate download urls.
  """

  def binary_path_components(self):
    """These strings are used as consecutive components of the path where a binary is fetched.

    This is also used in generating urls from --binaries-baseurls in PantsHosted."""
    return [self.os_name, self.arch_or_version]


class BinaryToolUrlGenerator(object):
  """Encapsulates the selection of urls to download for some binary tool.

  :API: public

  :class:`BinaryTool` subclasses can return an instance of a class mixing this in to
  get_external_url_generator(self) to download their file or archive from some specified url or set
  of urls.
  """

  @abstractmethod
  def generate_urls(self, version, host_platform):
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

  class NoBaseUrlsError(ValueError): pass

  def __init__(self, binary_request, baseurls):
    self._binary_request = binary_request

    if not baseurls:
      raise self.NoBaseUrlsError(
        "Error constructing pants-hosted urls for the {} binary: no baseurls were provided."
        .format(binary_request.name))
    self._baseurls = baseurls

  def generate_urls(self, _version, host_platform):
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
class BinaryRequest(datatype([
    'supportdir',
    'version',
    'name',
    'platform_dependent',
    # NB: this can be None!
    'external_url_generator',
    # NB: this can be None!
    'archiver',
])):
  """Describes a request for a binary to download."""

  def _full_name(self):
    if self.archiver:
      return '{}.{}'.format(self.name, self.archiver.extension)
    return self.name

  def get_download_path(self, host_platform):
    binary_path_components = [self.supportdir]
    if self.platform_dependent:
      # TODO(John Sirois): finish doc of the path structure expected under base_path.
      binary_path_components.extend(host_platform.binary_path_components())
    binary_path_components.extend([self.version, self._full_name()])
    return os.path.join(*binary_path_components)


class BinaryFetchRequest(datatype(['download_path', 'urls'])):
  """Describes a request to download a file."""

  @memoized_property
  def file_name(self):
    return os.path.basename(self.download_path)

  class NoDownloadUrlsError(ValueError): pass

  def __new__(cls, download_path, urls):
    this_object = super(BinaryFetchRequest, cls).__new__(
      cls, download_path, tuple(urls))

    if not this_object.urls:
      raise cls.NoDownloadUrlsError(
        "No urls were provided to {cls_name}: {obj!r}."
        .format(cls_name=cls.__name__, obj=this_object))

    return this_object


class BinaryToolFetcher(object):

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
        'Failed to fetch {name} binary from any source: ({error_msgs})'
        .format(name=name, error_msgs=', '.join(accumulated_errors)))

  @contextmanager
  def _select_binary_stream(self, name, urls):
    """Download a file from a list of urls, yielding a stream after downloading the file.

    URLs are tried in order until they succeed.

    :raises: :class:`BinaryToolFetcher.BinaryNotFound` if requests to all the given urls fail.
    """
    downloaded_successfully = False
    accumulated_errors = []
    for url in OrderedSet(urls):  # De-dup URLS: we only want to try each URL once.
      logger.info('Attempting to fetch {name} binary from: {url} ...'.format(name=name, url=url))
      try:
        with temporary_file() as dest:
          logger.debug("in BinaryToolFetcher: url={}, timeout_secs={}"
                       .format(url, self._timeout_secs))
          self._fetcher.download(url,
                                 listener=Fetcher.ProgressListener(),
                                 path_or_fd=dest,
                                 timeout_secs=self._timeout_secs)
          logger.info('Fetched {name} binary from: {url} .'.format(name=name, url=url))
          downloaded_successfully = True
          dest.seek(0)
          yield dest
          break
      except (IOError, Fetcher.Error, ValueError) as e:
        accumulated_errors.append('Failed to fetch binary from {url}: {error}'
                                  .format(url=url, error=e))
    if not downloaded_successfully:
      raise self.BinaryNotFound(name, accumulated_errors)

  def _do_fetch(self, download_path, file_name, urls):
    with safe_concurrent_creation(download_path) as downloadpath:
      with self._select_binary_stream(file_name, urls) as binary_tool_stream:
        with safe_open(downloadpath, 'wb') as bootstrapped_binary:
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

    logger.debug('Selected {binary} binary bootstrapped to: {path}'
                 .format(binary=file_name, path=bootstrapped_binary_path))
    return bootstrapped_binary_path


class BinaryUtil(object):
  """Wraps utility methods for finding binary executables."""

  class Factory(Subsystem):
    """
    :API: public
    """
    # N.B. `BinaryUtil` sources all of its options from bootstrap options, so that
    # `BinaryUtil` instances can be created prior to `Subsystem` bootstrapping. So
    # this options scope is unused, but required to remain a `Subsystem`.
    options_scope = 'binaries'

    @classmethod
    def create(cls):
      return cls._create_for_cls(BinaryUtil)

    @classmethod
    def _create_for_cls(cls, binary_util_cls):
      # NB: create is a class method to ~force binary fetch location to be global.
      options = cls.global_instance().get_options()
      binary_tool_fetcher = BinaryToolFetcher(
        bootstrap_dir=options.pants_bootstrapdir,
        timeout_secs=options.binaries_fetch_timeout_secs)
      return binary_util_cls(
        baseurls=options.binaries_baseurls,
        binary_tool_fetcher=binary_tool_fetcher,
        path_by_id=options.binaries_path_by_id,
        allow_external_binary_tool_downloads=options.allow_external_binary_tool_downloads)

  class MissingMachineInfo(TaskError):
    """Indicates that pants was unable to map this machine's OS to a binary path prefix."""
    pass

  class NoBaseUrlsError(TaskError):
    """Indicates that no urls were specified in pants.ini."""
    pass

  class BinaryResolutionError(TaskError):
    """Raised to wrap other exceptions raised in the select() method to provide context."""

    def __init__(self, binary_request, base_exception):
      super(BinaryUtil.BinaryResolutionError, self).__init__(
        "Error resolving binary request {}: {}".format(binary_request, base_exception),
        base_exception)

  def __init__(self, baseurls, binary_tool_fetcher, path_by_id=None,
               allow_external_binary_tool_downloads=True, uname_func=None):
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
    'linux': lambda release, machine: ('linux', machine),
    'darwin': lambda release, machine: ('darwin', release.split('.')[0]),
  }

  # FIXME(cosmicexplorer): we create a HostPlatform in this class instead of in the constructor
  # because we don't want to fail until a binary is requested. The HostPlatform should be a
  # parameter that gets lazily resolved by the v2 engine.
  @memoized_method
  def _host_platform(self):
    uname_result = self._uname_func()
    sysname, _, release, _, machine = uname_result
    os_id_key = sysname.lower()
    try:
      os_id_fun = self._ID_BY_OS[os_id_key]
      os_id_tuple = os_id_fun(release, machine)
    except KeyError:
      # TODO: test this!
      raise self.MissingMachineInfo(
        "Pants could not resolve binaries for the current host: platform '{}' was not recognized. "
        "Recognized platforms are: {}."
        .format(os_id_key, self._ID_BY_OS.keys()))
    try:
      os_name, arch_or_version = self._path_by_id[os_id_tuple]
      host_platform = HostPlatform(os_name, arch_or_version)
    except KeyError:
      # We fail early here because we need the host_platform to identify where to download binaries
      # to.
      raise self.MissingMachineInfo(
        "Pants could not resolve binaries for the current host. Update --binaries-path-by-id to "
        "find binaries for the current host platform {}.\n"
        "--binaries-path-by-id was: {}."
        .format(os_id_tuple, self._path_by_id))

    return host_platform

  def _get_download_path(self, binary_request):
    return binary_request.get_download_path(self._host_platform())

  def _get_url_generator(self, binary_request):

    external_url_generator = binary_request.external_url_generator

    logger.debug("self._allow_external_binary_tool_downloads: {}"
                 .format(self._allow_external_binary_tool_downloads))
    logger.debug("external_url_generator: {}".format(external_url_generator))

    if external_url_generator and self._allow_external_binary_tool_downloads:
      url_generator = external_url_generator
    else:
      if not self._baseurls:
        raise self.NoBaseUrlsError("--binaries-baseurls is empty.")
      url_generator = PantsHosted(binary_request=binary_request, baseurls=self._baseurls)

    return url_generator

  def _get_urls(self, url_generator, binary_request):
    return url_generator.generate_urls(binary_request.version, self._host_platform())

  def select(self, binary_request):
    """Fetches a file, unpacking it if necessary."""

    logger.debug("binary_request: {!r}".format(binary_request))

    try:
      download_path = self._get_download_path(binary_request)
    except self.MissingMachineInfo as e:
      raise self.BinaryResolutionError(binary_request, e)

    try:
      url_generator = self._get_url_generator(binary_request)
    except self.NoBaseUrlsError as e:
      raise self.BinaryResolutionError(binary_request, e)

    urls = self._get_urls(url_generator, binary_request)
    if not isinstance(urls, list):
      # TODO: add test for this error!
      raise self.BinaryResolutionError(
        binary_request,
        TypeError("urls must be a list: was '{}'.".format(urls)))
    fetch_request = BinaryFetchRequest(
      download_path=download_path,
      urls=urls)

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
      archiver=None)

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
      archiver=None)

  def select_script(self, supportdir, version, name):
    binary_request = self._make_deprecated_script_request(supportdir, version, name)
    return self.select(binary_request)
