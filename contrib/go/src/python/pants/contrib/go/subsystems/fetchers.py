# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import importlib
import logging
import os
import re
import shutil
import traceback
from abc import abstractmethod
from collections import namedtuple
from contextlib import closing, contextmanager

import requests
from pants.fs.archive import archiver_for_path
from pants.option.custom_types import dict_option
from pants.subsystem.subsystem import Subsystem
from pants.util.contextutil import temporary_dir, temporary_file
from pants.util.memo import memoized_method, memoized_property
from pants.util.meta import AbstractClass
from six.moves.urllib.parse import urlparse


class Fetcher(AbstractClass):
  """Knows how to interpret some remote import paths and fetch code to satisfy them."""

  class FetchError(Exception):
    """Indicates an error fetching remote code."""

  @abstractmethod
  def root(self, import_path):
    """Returns the root of the given remote import_path.

    The root is defined as the portion of the remote import path indicating the associated
    package's remote location; ie: for the remote import path of
    'github.com/docker/docker/daemon/events' it would be 'github.com/docker/docker'.

    Many remote import paths may share the same root; ie: all the 20+ docker packages hosted at
    https://github.com/docker/docker share the 'github.com/docker/docker' root.

    :param string import_path: The remote import path to extract the root from.
    :returns: The root portion of the import path.
    :rtype: string
    """

  @abstractmethod
  def fetch(self, go_remote_library, dest):
    """Fetches to remote library to the given dest dir.

    The dest dir provided will be an existing empty directory.

    :param go_remote_library: The library describing the remote package to fetch.
    :type: :class:`pants.contrib.go.targets.go_remote_library.GoRemoteLibrary`
    :param string dest: The path of an existing empty directory to extract package containing the
                        remote library's contents to.
    :raises: :class:`Fetcher.FetchError` if there was a problem fetching the remote package.
    """


class Fetchers(Subsystem):
  """A registry of installed :class:`Fetcher`s."""

  class AdvertisementError(Exception):
    """Indicates an error advertising a :class:`Fetcher`."""

  class InvalidAdvertisement(AdvertisementError):
    """Indicates the type submitted for advertisement is not valid."""

  class ConflictingAdvertisement(AdvertisementError):
    """Indicates a requested advertisement conflicts with an already-registered advertisement."""

  _FETCHERS = {}

  @classmethod
  def _fully_qualified_class_name(cls, clazz):
    return '{}.{}'.format(clazz.__module__, clazz.__name__)

  @classmethod
  def advertise(cls, fetcher_class, namespace=None):
    """Advertises a :class:`Fetcher` class available for installation.

    Fetcher implementations need not be registered unless one of the following is true:
    1. You wish to provide an alias to refer to the fetcher with for configuration.
    2. The fetcher class is a :class:`pants.subsystem.subsystem.Subsystem` that needs to be
       available for further configuration of its own.

    Un-advertised Non-Subsystem fetchers can be configured by their fully qualified class names.

    If a namespace is supplied, the fetcher class will be registered both by its fully qualified
    class name (the default), and under an alias formed from the namespace dotted with the simple
    class name of the fetcher.  If the supplied namespace is the empty string (''), then the alias
    becomes just the simple class name of the fetcher.  For example, for the fetcher class
    `medium.pants.go.UUCPFetcher` and a namespace of 'medium' the registered alias would be
    'medium.UUCPFetcher'.  Supplying a namespace of '' would simply register 'UUCPFetcher'.  In
    either case, the fully qualified class name of 'medium.pants.go.UUCPFetcher' would also be
    registered as an alias for the fetcher type.

    :param type fetcher_class: The :class:`Fetcher` subclass to advertise.
    :param string namespace: An optional string to prefix the `fetcher_class`'s simple class
                             `__name__` with (<namespace>.<simple class name>). If the namespace is
                             the emtpy string ('') then the `fetcher_class`'s simple class name
                             becomes the full alias with no prefixing.
    :raises: :class:`Fetchers.InvalidAdvertisement` If the given fetcher_class is not a fetcher
             subclass.
    :raises: :class:`Fetchers.ConflictingAdvertisement` If the given alias is already used.
    """
    # TODO(John Sirois): Find a sane way to map advertisements to documentation.  We could dump
    # out a list of all the aliases and the class docstring of the aliased fetcher class for
    # example, but this could simply be too much output for command line help (which also does not
    # allow control over the help string formatting - notably newlines cannot be dictated).
    if not issubclass(fetcher_class, Fetcher):
      raise cls.InvalidAdvertisement('The {} type is not a Fetcher'.format(fetcher_class))

    fully_qualified_fetcher_class_name = cls._fully_qualified_class_name(fetcher_class)
    cls._FETCHERS[fully_qualified_fetcher_class_name] = fetcher_class
    if namespace is not None:
      namespaced_key = ('{}.{}'.format(namespace, fetcher_class.__name__) if namespace
                        else fetcher_class.__name__)
      if namespaced_key != fully_qualified_fetcher_class_name:
        existing_alias = cls._FETCHERS.get(namespaced_key)
        if existing_alias and existing_alias != fetcher_class:
          raise cls.ConflictingAdvertisement('Cannot advertise {} as {!r} which already aliases {}'
                                             .format(fetcher_class, namespaced_key, existing_alias))
        cls._FETCHERS[namespaced_key] = fetcher_class

  @classmethod
  def alias(cls, fetcher_class):
    """Returns the most concise register alias for the given fetcher type.

    If no alias is registered, returns it's fully qualified class name.

    :param type fetcher_class: The fetcher class to look up an alias for.
    :raises: :class:`Fetchers.InvalidAdvertisement` if the given fetcher class is not a
             :class:`Fetcher`.
    """
    # Used internally to find the shortest alias for a fetcher.
    aliases = sorted((alias for alias, clazz in cls._FETCHERS.items() if clazz == fetcher_class),
                     key=lambda a: len(a))
    if aliases:
      # Shortest alias is friendliest alias.
      return aliases[0]
    else:
      if not issubclass(fetcher_class, Fetcher):
        raise cls.InvalidAdvertisement('The {} type can have no alias since its not a Fetcher'
                                       .format(fetcher_class))
      return cls._fully_qualified_class_name(fetcher_class)

  _DEFAULT_FETCHERS = {}

  @classmethod
  def _register_default(cls, regex, fetcher_class):
    # Used internally to register default shipped fetchers under their shortest alias for best
    # display in the command line help default. Should be called _after_ advertising an alias.
    # See the bottom of this file for the builtin advertisements and default registrations.
    aliases = sorted((alias for alias, clazz in cls._FETCHERS.items() if clazz == fetcher_class),
                     key=lambda a: len(a))
    alias = aliases[0] if aliases else cls._fully_qualified_class_name(fetcher_class)
    cls._DEFAULT_FETCHERS[regex] = alias

  @classmethod
  def dependencies(cls):
    return tuple(f for f in set(cls._FETCHERS.values()) if issubclass(f, Subsystem))

  options_scope = 'fetchers'

  @classmethod
  def register_options(cls, register):
    # TODO(John Sirois): Introduce a fetchers option that assigns names to fetchers for re-use
    # in mapping below which will change from a dict to a list of 2-tuples (regex, named_fetcher).
    # This will allow for the user configuring a fetcher several different ways and then controlling
    # match order by placing fetchers at the head of the list to handle special cases before
    # falling through to more general matchers.
    # Tracked at: https://github.com/pantsbuild/pants/issues/2018
    register('--mapping', metavar='<mapping>', type=dict_option, default=cls._DEFAULT_FETCHERS,
             advanced=True,
             help="A mapping from a remote import path matching regex to a fetcher type to use "
                  "to fetch the remote sources.  Fetcher types are fully qualified class names "
                  "or else an installed alias for a fetcher type; ie the builtin "
                  "`contrib.go.subsystems.fetchers.ArchiveFetcher` is aliased as 'ArchiveFetcher'.")

  class GetFetchError(Exception):
    """Indicates an error finding an appropriate Fetcher."""

  class UnfetchableRemote(GetFetchError):
    """Indicates no Fetcher claims the given remote import path."""

  class InvalidFetcherError(GetFetchError):
    """Indicates an invalid Fetcher type or an un-instantiable Fetcher."""

  class InvalidFetcherModule(InvalidFetcherError):
    """Indicates the Fetcher's module cannot be imported."""

  class InvalidFetcherClassName(InvalidFetcherError):
    """Indicates the given fetcher class name cannot be imported."""

  class InvalidFetcherType(InvalidFetcherError):
    """Indicates the given fetcher type if not, in fact, a Fetcher."""

  @classmethod
  def _fetcher(cls, name):
    fetcher_class = cls._FETCHERS.get(name)
    if fetcher_class:
      return fetcher_class

    fetcher_module, _, fetcher_class_name = name.rpartition('.')
    try:
      module = importlib.import_module(fetcher_module)
    except ImportError:
      traceback.print_exc()
      raise cls.InvalidFetcherModule('Failed to import fetcher {} from module {}'
                                     .format(name, fetcher_module))
    if not hasattr(module, fetcher_class_name):
      raise cls.InvalidFetcherClassName('Failed to find fetcher class {} in module {}'
                                        .format(fetcher_class_name, fetcher_module))
    fetcher_class = getattr(module, fetcher_class_name)
    if not issubclass(fetcher_class, Fetcher):
      raise cls.InvalidFetcherType('Fetcher {} must be a {}'
                                   .format(name, cls._fully_qualified_class_name(fetcher_class)))
    return fetcher_class

  @memoized_property
  def _fetchers(self):
    fetchers = []
    for regex, fetcher in self.get_options().mapping.items():
      matcher = re.compile(regex)

      fetcher_class = self._fetcher(fetcher)
      fetcher = (fetcher_class.global_instance() if issubclass(fetcher_class, Subsystem)
                 else fetcher_class())
      fetchers.append((matcher, fetcher))
    return fetchers

  @memoized_method
  def get_fetcher(self, import_path):
    """Returns a :class:`Fetcher` capable of resolving the given remote import path.

    :param string import_path: The remote import path to fetch.
    :returns: A fetcher capable of fetching the given `import_path`.
    :rtype: :class:`Fetcher`
    :raises: :class:`Fetchers.UnfetchableRemote` if no fetcher was found that could handle the
             given `import_path`.
    """
    for matcher, fetcher in self._fetchers:
      match = matcher.match(import_path)
      if match and match.start() == 0:
        return fetcher
    raise self.UnfetchableRemote(import_path)


class ArchiveFetcher(Fetcher, Subsystem):
  """A fetcher that knows how to find archives for remote import paths and unpack them."""

  logger = logging.getLogger(__name__)

  class UrlInfo(namedtuple('UrlInfo', ['url_format', 'default_rev', 'strip_level'])):
    def rev(self, go_remote_library):
      return go_remote_library.rev or self.default_rev

  options_scope = 'archive-fetcher'

  _DEFAULT_MATCHERS = {
    r'bitbucket.org/(?P<user>[^/]+)/(?P<repo>[^/]+)':
      UrlInfo(url_format='https://bitbucket.org/\g<user>/\g<repo>/get/{rev}.tar.gz',
              default_rev='tip',
              strip_level=1),
    r'github.com/(?P<user>[^/]+)/(?P<repo>[^/]+)':
      UrlInfo(url_format='https://github.com/\g<user>/\g<repo>/archive/{rev}.tar.gz',
              default_rev='master',
              strip_level=1),
  }

  @classmethod
  def register_options(cls, register):
    register('--matchers', metavar='<mapping>', type=dict_option,
             default=cls._DEFAULT_MATCHERS, advanced=True,
             # NB: The newlines used below are for reading the logical structure here only.
             # They're converted to a single space by the help formatting and the resulting long
             # line of help text is simply wrapped.
             help="A mapping from a remote import path matching regex to an UrlInfo struct "
                  "describing how to fetch and unpack a remote import path.  The UrlInfo struct is "
                  "a 3-tuple with the following slots:\n"
                  "0. An url format string that is supplied to the regex match\'s `.template` "
                  "method and then formatted with the remote import path\'s `rev` and `pkg`.\n"
                  "1. The default revision string to use when no `rev` is supplied; ie 'HEAD' or "
                  "'master' for git.\n"
                  "2. An integer indicating the number of leading path components to strip from "
                  "files upacked from the archive.\n"
                  "\n"
                  "An example configuration that works against github.com is:\n"
                  "{r'github.com/(?P<user>[^/]+)/(?P<repo>[^/]+)':\n"
                  " ('https://github.com/\g<user>/\g<repo>/archive/{rev}.zip', 'master', 1)}")
    register('--buffer-size', metavar='<bytes>', type=int, advanced=True,
             default=10 * 1024,  # 10KB in case jumbo frames are in play.
             help='The number of bytes of archive content to buffer in memory before flushing to '
                  'disk when downloading an archive.')

  @memoized_property
  def _matchers(self):
    matchers = []
    for regex, info in self.get_options().matchers.items():
      matcher = re.compile(regex)
      url_info = self.UrlInfo(*info)
      matchers.append((matcher, url_info))
    return matchers

  @memoized_method
  def _matcher(self, import_path):
    for matcher, url_info in self._matchers:
      match = matcher.search(import_path)
      if match and match.start() == 0:
        return match, url_info
    raise self.FetchError("Don't know how to fetch {}".format(import_path))

  def root(self, import_path):
    match, _ = self._matcher(import_path)
    return match.string[:match.end()]

  def fetch(self, go_remote_library, dest):
    match, url_info = self._matcher(go_remote_library.import_path)
    archive_url = match.expand(url_info.url_format).format(rev=url_info.rev(go_remote_library),
                                                           pkg=go_remote_library.pkg)
    try:
      archiver = archiver_for_path(archive_url)
    except ValueError:
      raise self.FetchError("Don't know how to unpack archive at url {}".format(archive_url))

    with self._fetch(archive_url) as archive:
      if url_info.strip_level == 0:
        archiver.extract(archive, dest)
      else:
        with temporary_dir() as scratch:
          archiver.extract(archive, scratch)
          for dirpath, dirnames, filenames in os.walk(scratch, topdown=True):
            if dirpath != scratch:
              relpath = os.path.relpath(dirpath, scratch)
              relpath_components = relpath.split(os.sep)
              if len(relpath_components) == url_info.strip_level and (dirnames or filenames):
                for path in dirnames + filenames:
                  src = os.path.join(dirpath, path)
                  dst = os.path.join(dest, path)
                  shutil.move(src, dst)
                del dirnames[:]  # Stops the walk.

  @contextmanager
  def _fetch(self, url):
    parsed = urlparse(url)
    if not parsed.scheme or parsed.scheme == 'file':
      yield parsed.path
    else:
      with self._download(url) as download_path:
        yield download_path

  @contextmanager
  def _download(self, url):
    # TODO(jsirois): Wrap with workunits, progress meters, checksums.
    self.logger.info('Downloading {}...'.format(url))
    with closing(requests.get(url, stream=True)) as res:
      if not res.status_code == requests.codes.ok:
        raise self.FetchError('Failed to download {} ({} error)'.format(url, res.status_code))
      with temporary_file() as archive_fp:
        # NB: Archives might be very large so we play it safe and buffer them to disk instead of
        # memory before unpacking.
        for chunk in res.iter_content(chunk_size=self.get_options().buffer_size):
          archive_fp.write(chunk)
        archive_fp.close()
        res.close()
        yield archive_fp.name


# All builtin fetchers should be advertised and registered as defaults here, 1st advertise,
# then register:
Fetchers.advertise(ArchiveFetcher, namespace='')
Fetchers._register_default(r'github.com/.*', ArchiveFetcher)
