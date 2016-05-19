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
from pants.subsystem.subsystem import Subsystem
from pants.util.contextutil import temporary_dir, temporary_file
from pants.util.memo import memoized_method, memoized_property
from pants.util.meta import AbstractClass
from six.moves.urllib.parse import urlparse

from pants.contrib.go.targets.go_remote_library import GoRemoteLibrary


logger = logging.getLogger(__name__)


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

    This is called the import-prefix in 'https://golang.org/cmd/go/#hdr-Remote_import_paths'

    :param string import_path: The remote import path to extract the root from.
    :returns: The root portion of the import path.
    :rtype: string
    """

  @abstractmethod
  def fetch(self, import_path, dest, rev=None):
    """Fetches to remote library to the given dest dir.

    The dest dir provided will be an existing empty directory.

    :param string import_path: The remote import path to fetch.
    :param string rev: The version to fetch - may be `None` or empty indicating the latest version
                       should be fetched.
    :param string dest: The path of an existing empty directory to extract package containing the
                        remote library's contents to.
    :raises: :class:`Fetcher.FetchError` if there was a problem fetching the remote package.
    """


class Fetchers(Subsystem):
  """A registry of installed remote code fetchers."""

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
  def subsystem_dependencies(cls):
    return tuple(f for f in set(cls._FETCHERS.values()) if issubclass(f, Subsystem))

  options_scope = 'go-fetchers'
  deprecated_options_scope = 'fetchers'
  deprecated_options_scope_removal_version = '1.2.0'

  @classmethod
  def register_options(cls, register):
    # TODO(John Sirois): Introduce a fetchers option that assigns names to fetchers for re-use
    # in mapping below which will change from a dict to a list of 2-tuples (regex, named_fetcher).
    # This will allow for the user configuring a fetcher several different ways and then controlling
    # match order by placing fetchers at the head of the list to handle special cases before
    # falling through to more general matchers.
    # Tracked at: https://github.com/pantsbuild/pants/issues/2018
    register('--mapping', metavar='<mapping>', type=dict, default=cls._DEFAULT_FETCHERS,
             advanced=True,
             help="A mapping from a remote import path matching regex to a fetcher type to use "
                  "to fetch the remote sources.  The regex must match the beginning of the remote "
                  "import path; no '^' anchor is needed, it is assumed.  The Fetcher types are "
                  "fully qualified class names or else an installed alias for a fetcher type; "
                  "I.e., the built-in 'contrib.go.subsystems.fetchers.ArchiveFetcher' is aliased "
                  "as 'ArchiveFetcher'.")

  class GetFetcherError(Exception):
    """Indicates an error finding an appropriate Fetcher."""

  class UnfetchableRemote(GetFetcherError):
    """Indicates no Fetcher claims the given remote import path."""

  class InvalidFetcherError(GetFetcherError):
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
  def maybe_get_fetcher(self, import_path):
    """Returns a :class:`Fetcher` capable of resolving the given remote import path.

    :param string import_path: The remote import path to fetch.
    :returns: A fetcher capable of fetching the given `import_path` or `None` if no capable fetcher
              was found.
    :rtype: :class:`Fetcher`
    """
    for matcher, fetcher in self._fetchers:
      match = matcher.match(import_path)
      if match and match.start() == 0:
        return fetcher
    return None

  def get_fetcher(self, import_path):
    """Returns a :class:`Fetcher` capable of resolving the given remote import path.

    :param string import_path: The remote import path to fetch.
    :returns: A fetcher capable of fetching the given `import_path`.
    :rtype: :class:`Fetcher`
    :raises: :class:`Fetcher.UnfetchableRemote` if no fetcher is registered to handle the given
             import path.
    """
    fetcher = self.maybe_get_fetcher(import_path)
    if not fetcher:
      raise self.UnfetchableRemote(import_path)
    return fetcher


class ArchiveFetcher(Fetcher, Subsystem):
  """A fetcher that knows how find archives for remote import paths and unpack them."""

  class UrlInfo(namedtuple('UrlInfo', ['url_format', 'default_rev', 'strip_level'])):
    def rev(self, rev):
      return rev or self.default_rev

  options_scope = 'go-archive-fetcher'
  deprecated_options_scope = 'archive-fetcher'
  deprecated_options_scope_removal_version = '1.2.0'

  _DEFAULT_MATCHERS = {
    r'bitbucket\.org/(?P<user>[^/]+)/(?P<repo>[^/]+)':
      UrlInfo(url_format='https://bitbucket.org/\g<user>/\g<repo>/get/{rev}.tar.gz',
              default_rev='tip',
              strip_level=1),
    r'github\.com/(?P<user>[^/]+)/(?P<repo>[^/]+)':
      UrlInfo(url_format='https://github.com/\g<user>/\g<repo>/archive/{rev}.tar.gz',
              default_rev='master',
              strip_level=1),
    r'golang\.org/x/(?P<repo>[^/]+)':
      UrlInfo(url_format='https://github.com/golang/\g<repo>/archive/{rev}.tar.gz',
              default_rev='master',
              strip_level=1),
    r'google\.golang\.org/.*':
      UrlInfo(url_format='{meta_repo_url}/+archive/{rev}.tar.gz',
              default_rev='master',
              strip_level=0),
  }

  @classmethod
  def register_options(cls, register):
    register('--matchers', metavar='<mapping>', type=dict,
             default=cls._DEFAULT_MATCHERS, advanced=True,
             help="A mapping from a remote import path matching regex to an UrlInfo struct "
                  "describing how to fetch and unpack a remote import path.  The regex must match "
                  "the beginning of the remote import path (no '^' anchor is needed, it is "
                  "assumed) until the first path element that is contained in the archive. (e.g. for "
                  "'bazil.org/fuse/fs', which lives in the archive of 'bazil.org/fuse', it must match "
                  "'bazil.org/fuse'.) The UrlInfo struct is a 3-tuple with the following slots:\n"
                  "0. An url format string that is supplied to the regex match\'s `.template` "
                  "method and then formatted with the remote import path\'s `rev`, `import_prefix`, "
                  "and `pkg`.\n"
                  "1. The default revision string to use when no `rev` is supplied; ie 'HEAD' or "
                  "'master' for git. "
                  "2. An integer indicating the number of leading path components to strip from "
                  "files upacked from the archive. "
                  "An example configuration that works against github.com is: "
                  "{r'github.com/(?P<user>[^/]+)/(?P<repo>[^/]+)': "
                  " ('https://github.com/\g<user>/\g<repo>/archive/{rev}.zip', 'master', 1)}")
    register('--buffer-size', metavar='<bytes>', type=int, advanced=True,
             default=10 * 1024,  # 10KB in case jumbo frames are in play.
             help='The number of bytes of archive content to buffer in memory before flushing to '
                  'disk when downloading an archive.')
    register('--retries', default=1, advanced=True,
             help='How many times to retry to fetch a remote library.')
    register('--prefixes', metavar='<paths>', type=list, advanced=True,
             fromfile=True, default=[],
             help="Known import-prefixes for go packages")

  @memoized_property
  def _matchers(self):
    matchers = []
    for regex, info in self.get_options().matchers.items():
      matcher = re.compile(regex)
      url_info = self.UrlInfo(*info)
      matchers.append((matcher, url_info))
    return matchers

  @memoized_property
  def _prefixes(self):
    """Returns known prefixes of Go packages that are the root of archives."""
    # The Go get meta protocol involves reading the HTML to find a meta tag with the name go-import
    # that lists a prefix. Knowing this prefix ahead of time allows the ArchiveFetcher to fetch
    # the archive. This is especially useful if running in an environment where there is no
    # network access other than to a repository of tarballs of the source.
    return self.get_options().prefixes

  @memoized_method
  def _matcher(self, import_path):
    for matcher, url_info in self._matchers:
      match = matcher.search(import_path)
      if match and match.start() == 0:
        return match, url_info
    raise self.FetchError("Don't know how to fetch {}".format(import_path))

  def root(self, import_path):
    for prefix in self._prefixes:
      if import_path.startswith(prefix):
        return prefix
    match, _ = self._matcher(import_path)
    return match.string[:match.end()]

  def fetch(self, import_path, dest, rev=None, url_info=None, meta_repo_url=None):
    match, url_info = self._matcher(import_path)
    pkg = GoRemoteLibrary.remote_package_path(self.root(import_path), import_path)
    archive_url = match.expand(url_info.url_format).format(
      rev=url_info.rev(rev), pkg=pkg, import_prefix=self.root(import_path),
      meta_repo_url=meta_repo_url)
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

  def session(self):
    session = requests.session()
    # Override default http adapters with a retriable one.
    retriable_http_adapter = requests.adapters.HTTPAdapter(max_retries=self.get_options().retries)
    session.mount("http://", retriable_http_adapter)
    session.mount("https://", retriable_http_adapter)
    return session

  @contextmanager
  def _download(self, url):
    # TODO(jsirois): Wrap with workunits, progress meters, checksums.
    logger.info('Downloading {}...'.format(url))
    with closing(self.session().get(url, stream=True)) as res:
      if res.status_code != requests.codes.ok:
        raise self.FetchError('Failed to download {} ({} error)'.format(url, res.status_code))
      with temporary_file() as archive_fp:
        # NB: Archives might be very large so we play it safe and buffer them to disk instead of
        # memory before unpacking.
        for chunk in res.iter_content(chunk_size=self.get_options().buffer_size):
          archive_fp.write(chunk)
        archive_fp.close()
        res.close()
        yield archive_fp.name


class GopkgInFetcher(Fetcher, Subsystem):
  """A fetcher implementing the URL re-writing protocol of gopkg.in.

  The protocol rewrites a versioned remote import path scheme to a github URL + rev and delegates
  to the ArchiveFetcher to do the rest.

  The versioning URL scheme is described here: http://gopkg.in
  NB: Unfortunately gopkg.in does not implement the <meta/> tag re-direction scheme defined in
  `go help importpath` so we are forced to implement their re-direction protocol instead of using
  the more general <meta/> tag protocol.
  """
  options_scope = 'gopkg-in'
  deprecated_options_scope = 'gopkg.in'
  deprecated_options_scope_removal_version = '1.2.0'

  @classmethod
  def subsystem_dependencies(cls):
    return (ArchiveFetcher,)

  @property
  def _fetcher(self):
    return ArchiveFetcher.global_instance()

  def root(self, import_path):
    user, package, raw_rev = self._extract_root_components(import_path)
    pkg = '{}.{}'.format(package, raw_rev)
    return 'gopkg.in/{}/{}'.format(user, pkg) if user else 'gopkg.in/{}'.format(pkg)

  # VisibleForTesting
  def _do_fetch(self, import_path, dest, rev=None):
    return self._fetcher.fetch(import_path, dest, rev=rev)

  def fetch(self, import_path, dest, rev=None, meta_repo_url=None):
    github_root, github_rev = self._map_github_root_and_rev(import_path, rev)
    self._do_fetch(github_root, dest, rev=rev or github_rev)

  # GitHub username rules allow us to bank on pkg.v1 being the package/rev and never a user.
  # Could not find docs for this, but trying to sign up as 'pkg.v1' on 11/17/2015 yields:
  # "Username may only contain alphanumeric characters or single hyphens, and cannot begin or end
  #  with a hyphen."
  _USER_PACKAGE_AND_REV_RE = re.compile(r'(?:(?P<user>[^/]+)/)?(?P<package>[^/]+).(?P<rev>v[0-9]+)')

  @memoized_method
  def _extract_root_components(self, import_path):
    components = import_path.split('/', 1)

    domain = components.pop(0)
    if 'gopkg.in' != domain:
      raise self.FetchError('Can only fetch packages for gopkg.in, given: {}'.format(import_path))

    match = self._USER_PACKAGE_AND_REV_RE.match(components[0])
    if not match:
      raise self.FetchError('Invalid gopkg.in package and rev in: {}'.format(import_path))

    user, package, raw_rev = match.groups()
    return user, package, raw_rev

  @memoized_method
  def _map_github_root_and_rev(self, import_path, rev=None):
    user, package, raw_rev = self._extract_root_components(import_path)
    user = user or 'go-{}'.format(package)
    rev = rev or self._find_highest_compatible(user, package, raw_rev)
    github_root = 'github.com/{user}/{pkg}'.format(user=user, pkg=package)
    logger.debug('Resolved {} to {} at rev {}'.format(import_path, github_root, rev))
    return github_root, rev

  class ApiError(Fetcher.FetchError):
    """Indicates a compatible version could not be found due to github API errors."""

  class NoMatchingVersionError(Fetcher.FetchError):
    """Indicates versions were found, but none matched."""

  class NoVersionsError(Fetcher.FetchError):
    """Indicates no versions were found even there there were no github API errors - unexpected."""

  def _find_highest_compatible(self, user, repo, raw_rev):
    candidates = set()
    errors = []

    def collect_refs(search):
      try:
        return candidates.update(self._iter_refs(user, repo, search))
      except self.FetchError as e:
        errors.append(e)

    collect_refs('refs/tags')
    highest_compatible = self._select_highest_compatible(candidates, raw_rev)
    if highest_compatible:
      return highest_compatible

    collect_refs('refs/heads')
    highest_compatible = self._select_highest_compatible(candidates, raw_rev)
    if highest_compatible:
      return highest_compatible

    # http://labix.org/gopkg.in defines the v0 fallback as master.
    if raw_rev == 'v0':
      return 'master'

    if len(errors) == 2:
      raise self.ApiError('Failed to fetch both tags and branches:\n\t{}\n\t{}'
                          .format(errors[0], errors[1]))
    elif not candidates:
      raise self.NoVersionsError('Found no tags or branches for github.com/{user}/{repo} - this '
                                 'is unexpected.'.format(user=user, repo=repo))
    elif errors:
      raise self.FetchError('Found no tag or branch for github.com/{user}/{repo} to match {rev}, '
                            'but encountered an error while searching:\n\t{}', errors.pop())
    else:
      raise self.NoMatchingVersionError('Found no tags or branches for github.com/{user}/{repo} '
                                        'compatible with {rev} amongst these refs:\n\t{refs}'
                                        .format(user=user, repo=repo, rev=raw_rev,
                                                refs='\n\t'.join(sorted(candidates))))

  # VisibleForTesting
  def _do_get(self, url):
    res = self._fetcher.session().get(url)
    if res.status_code != requests.codes.ok:
      raise self.FetchError('Failed to scan for the highest compatible version of {} ({} error)'
                            .format(url, res.status_code))
    return res.json()

  def _do_get_json(self, url):
    try:
      return self._do_get(url)
    except requests.RequestException as e:
      raise self.FetchError('Failed to scan for the highest compatible version of {} ({} error)'
                            .format(url, e))

  def _iter_refs(self, user, repo, search):
    # See: https://developer.github.com/v3/git/refs/#get-all-references
    # https://api.github.com/repos/{user}/{repo}/git/refs/tags
    # https://api.github.com/repos/{user}/{repo}/git/refs/heads
    # [{"ref": "refs/heads/v1", ...}, ...]
    url = ('https://api.github.com/repos/{user}/{repo}/git/{search}'
           .format(user=user, repo=repo, search=search))

    json = self._do_get_json(url)
    for ref in json:
      ref_name = ref.get('ref')
      if ref_name:
        components = ref_name.split(search + '/', 1)
        if len(components) == 2:
          prefix, raw_ref = components
          yield raw_ref

  class Match(namedtuple('Match', ['minor', 'patch', 'candidate'])):
    """A gopkg.in major version match that is suitable for simple sorting of highest match."""

  def _select_highest_compatible(self, candidates, raw_rev):
    prefix = raw_rev + '.'
    matches = []
    for candidate in candidates:
      if candidate == raw_rev:
        matches.append(self.Match(minor=0, patch=0, candidate=candidate))
      elif candidate.startswith(prefix):
        rest = candidate[len(prefix):]
        xs = rest.split('.', 1)
        try:
          minor = int(xs[0])
          patch = (0 if len(xs) == 1 else int(xs[1]))
          matches.append(self.Match(minor, patch, candidate))
        except ValueError:
          # The candidates come from all tag and branch names in the repo; so there could be
          # 'vX.non_numeric_string' candidates that do not confirm to gopkg.in's 'vX.(Y.(Z))'
          # scheme and so we just skip past those.
          pass
    if not matches:
      return None
    else:
      match = max(matches, key=lambda match: match.candidate)
      return match.candidate


# All builtin fetchers should be advertised and registered as defaults here, 1st advertise,
# then register:
Fetchers.advertise(GopkgInFetcher, namespace='')
Fetchers._register_default(r'gopkg\.in/.*', GopkgInFetcher)

Fetchers.advertise(ArchiveFetcher, namespace='')
Fetchers._register_default(r'bitbucket\.org/.*', ArchiveFetcher)
Fetchers._register_default(r'github\.com/.*', ArchiveFetcher)
Fetchers._register_default(r'golang\.org/x/.*', ArchiveFetcher)
Fetchers._register_default(r'google\.golang\.org/.*', ArchiveFetcher)
