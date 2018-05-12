# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import posixpath
import shutil
from abc import abstractmethod
from contextlib import contextmanager

from twitter.common.collections import OrderedSet

from pants.base.build_environment import get_buildroot
from pants.base.deprecated import deprecated
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
  """???"""

  def binary_path_components(self):
    """These strings are used as consecutive components of the path where a binary is fetched.

    This is also used in generating urls from --binaries-baseurls in PantsHosted."""
    return [self.os_name, self.arch_or_version]


class BinaryToolUrlGenerator(object):
  """???"""

  @abstractmethod
  def generate_urls(self, version, host_platform):
    """???"""
    pass


class PantsHosted(BinaryToolUrlGenerator):
  """
  TODO: ???

  Note that "pants-hosted" is referring to the organization of the urls being specific to pants. It
  also happens that most binaries are downloaded from S3 hosting at binaries.pantsbuild.org by
  default.
  """

  class NoBaseUrlsError(ValueError):
    """???"""
    pass

  def __init__(self, binary_request, baseurls):
    self._binary_request = binary_request

    if not baseurls:
      raise self.NoBaseUrlsError(
        "Error constructing pants-hosted urls for the {} binary: no baseurls were provided."
        .format(binary_request.name))
    self._baseurls = baseurls

  def generate_urls(self, _version, host_platform):
    """???"""
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
    'url_generator',
    # NB: this can be None!
    'archiver',
])):
  """???"""

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
  """???"""

  @memoized_property
  def file_name(self):
    return os.path.basename(self.download_path)

  class NoDownloadUrlsError(ValueError):
    """???"""
    pass

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
    return Fetcher(get_buildroot())

  def __init__(self, bootstrap_dir, timeout_secs, fetcher=None, ignore_cached_download=False):
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
    """???"""
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


class BinaryUtilPrivate(object):
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
      return cls._create_for_cls(BinaryUtilPrivate)

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
        force_baseurls=options.force_baseurls)

  class MissingMachineInfo(TaskError):
    """Indicates that pants was unable to map this machine's OS to a binary path prefix."""
    pass

  class NoBaseUrlsError(TaskError):
    """Indicates that no urls were specified in pants.ini."""
    pass

  class BinaryResolutionError(TaskError):
    """???"""

    def __init__(self, binary_request, base_exception):
      super(BinaryUtilPrivate.BinaryResolutionError, self).__init__(
        "Error resolving binary request {}: {}".format(binary_request, base_exception),
        base_exception)

  def __init__(self, baseurls, binary_tool_fetcher, path_by_id=None, force_baseurls=False,
               uname_func=None):
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
    # TODO: add back doc for uname_func!
    """
    self._baseurls = baseurls
    self._binary_tool_fetcher = binary_tool_fetcher

    self._path_by_id = SUPPORTED_PLATFORM_NORMALIZED_NAMES.copy()
    if path_by_id:
      self._path_by_id.update((tuple(k), tuple(v)) for k, v in path_by_id.items())

    self._force_baseurls = force_baseurls
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
    url_generator = binary_request.url_generator

    logger.debug("self._force_baseurls: {}".format(self._force_baseurls))
    logger.debug("url_generator: {}".format(url_generator))
    if self._force_baseurls or not url_generator:
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
      url_generator=None,
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
      url_generator=None,
      archiver=None)

  def select_script(self, supportdir, version, name):
    binary_request = self._make_deprecated_script_request(supportdir, version, name)
    return self.select(binary_request)


class BinaryUtil(BinaryUtilPrivate):
  """A temporary stub to express the fact that public access to BinaryUtil is now deprecated.

  After deprecation is complete, the base class will be renamed BinaryUtil, and it will not
  be considered part of the public Pants API.

  :API: public
  """

  @deprecated(removal_version='1.8.0.dev0', hint_message='Use NativeTool or Script instead.')
  def __init__(self, *args, **kwargs):
    super(BinaryUtil, self).__init__(*args, **kwargs)

  class Factory(BinaryUtilPrivate.Factory):
    """
    :API: public
    """

    @classmethod
    @deprecated(removal_version='1.8.0.dev0', hint_message='Use NativeTool or Script instead.')
    def create(cls):
      return cls._create_for_cls(BinaryUtilPrivate)
