# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import pkgutil
import subprocess
from contextlib import contextmanager

from six import string_types

from pants.base.revision import Revision
from pants.util.contextutil import temporary_dir


logger = logging.getLogger(__name__)


class Distribution(object):
  """Represents a java distribution - either a JRE or a JDK installed on the local system.

  In particular provides access to the distribution's binaries; ie: java while ensuring basic
  constraints are met.  For example a minimum version can be specified if you know need to compile
  source code or run bytecode that exercise features only available in that version forward.
  """

  class Error(Exception):
    """Indicates an invalid java distribution."""

  _CACHE = {}

  @classmethod
  def cached(cls, minimum_version=None, maximum_version=None, jdk=False):
    def scan_constraint_match():
      # Convert strings to Revision objects for apples-to-apples comparison.
      max_version = cls._parse_java_version("maximum_version", maximum_version)
      min_version = cls._parse_java_version("minimum_version", minimum_version)

      for dist in cls._CACHE.values():
        if min_version and dist.version < min_version:
          continue
        if max_version and dist.version > max_version:
          continue
        if jdk and not dist.jdk:
          continue
        return dist

    key = (minimum_version, maximum_version, jdk)
    dist = cls._CACHE.get(key)
    if not dist:
      dist = scan_constraint_match()
      if not dist:
        dist = cls.locate(minimum_version=minimum_version, maximum_version=maximum_version, jdk=jdk)
      cls._CACHE[key] = dist
    return dist

  @classmethod
  def locate(cls, minimum_version=None, maximum_version=None, jdk=False):
    """Finds a java distribution that meets any given constraints and returns it.

    First looks in JDK_HOME and JAVA_HOME if defined falling back to a search on the PATH.
    Raises Distribution.Error if no suitable java distribution could be found.
    """
    def home_bin_path(home_env_var):
      home = os.environ.get(home_env_var)
      return os.path.join(home, 'bin') if home else None

    def search_path():
      yield home_bin_path('JDK_HOME')
      yield home_bin_path('JAVA_HOME')
      path = os.environ.get('PATH')
      if path:
        for p in path.strip().split(os.pathsep):
          yield p

    for path in filter(None, search_path()):
      try:
        dist = cls(bin_path=path, minimum_version=minimum_version,
                   maximum_version=maximum_version, jdk=jdk)
        dist.validate()
        logger.debug('Located {} for constraints: minimum_version {}, maximum_version {}, jdk {}'
                     .format(dist, minimum_version, maximum_version, jdk))
        return dist
      except (ValueError, cls.Error):
        pass

    raise cls.Error('Failed to locate a {} distribution with minimum_version {}, maximum_version {}'
                    .format('JDK' if jdk else 'JRE', minimum_version, maximum_version))

  @staticmethod
  def _parse_java_version(name, version):
    # Java version strings have been well defined since release 1.3.1 as defined here:
    #  http://www.oracle.com/technetwork/java/javase/versioning-naming-139433.html
    # These version strings comply with semver except that the traditional pre-release semver
    # slot (the 4th) can be delimited by an _ in the case of update releases of the jdk.
    # We accommodate that difference here.
    if isinstance(version, string_types):
      version = Revision.semver(version.replace('_', '-'))
    if version and not isinstance(version, Revision):
      raise ValueError('{} must be a string or a Revision object, given: {}'.format(name, version))
    return version

  @staticmethod
  def _is_executable(path):
    return os.path.isfile(path) and os.access(path, os.X_OK)

  def __init__(self, bin_path='/usr/bin', minimum_version=None, maximum_version=None, jdk=False):
    """Creates a distribution wrapping the given bin_path.

    :param string bin_path: the path to the java distributions bin dir
    :param minimum_version: a modified semantic version string or else a Revision object
    :param maximum_version: a modified semantic version string or else a Revision object
    :param bool jdk: ``True`` to require the distribution be a JDK vs a JRE
    """

    if not os.path.isdir(bin_path):
      raise ValueError('The specified distribution path is invalid: {}'.format(bin_path))
    self._bin_path = bin_path

    self._minimum_version = self._parse_java_version("minimum_version", minimum_version)
    self._maximum_version = self._parse_java_version("maximum_version", maximum_version)

    self._jdk = jdk

    self._home_path = None
    self._is_jdk = False
    self._system_properties = None
    self._version = None
    self._validated_binaries = {}

  @property
  def jdk(self):
    self.validate()
    return self._is_jdk

  @property
  def system_properties(self):
    """Returns a dict containing the system properties of this java distribution."""
    return dict(self._get_system_properties(self.java))

  @property
  def version(self):
    """Returns the distribution version.

    Raises Distribution.Error if this distribution is not valid according to the configured
    constraints.
    """
    return self._get_version(self.java)

  def find_libs(self, names):
    """Looks for jars in the distribution lib folder(s).

    If the distribution is a JDK, both the `lib` and `jre/lib` dirs will be scanned.
    The endorsed and extension dirs are not checked.

    :param list names: jar file names
    :return: list of paths to requested libraries
    :raises: `Distribution.Error` if any of the jars could not be found.
    """
    def collect_existing_libs():
      def lib_paths():
        yield os.path.join(self.home, 'lib')
        if self.jdk:
          yield os.path.join(self.home, 'jre', 'lib')

      for name in names:
        for path in lib_paths():
          lib_path = os.path.join(path, name)
          if os.path.exists(lib_path):
            yield lib_path
            break
        else:
          raise Distribution.Error('Failed to locate {} library'.format(name))

    return list(collect_existing_libs())

  @property
  def home(self):
    """Returns the distribution JAVA_HOME."""
    if not self._home_path:
      home = self._get_system_properties(self.java)['java.home']
      # The `jre/bin/java` executable in a JDK distribution will report `java.home` as the jre dir,
      # so we check for this and re-locate to the containing jdk dir when present.
      if os.path.basename(home) == 'jre':
        jdk_dir = os.path.dirname(home)
        if self._is_executable(os.path.join(jdk_dir, 'bin', 'javac')):
          home = jdk_dir
      self._home_path = home
    return self._home_path

  @property
  def java(self):
    """Returns the path to this distribution's java command.

    If this distribution has no valid java command raises Distribution.Error.
    """
    return self.binary('java')

  def binary(self, name):
    """Returns the path to the command of the given name for this distribution.

    For example: ::

        >>> d = Distribution()
        >>> jar = d.binary('jar')
        >>> jar
        '/usr/bin/jar'
        >>>

    If this distribution has no valid command of the given name raises Distribution.Error.
    If this distribution is a JDK checks both `bin` and `jre/bin` for the binary.
    """
    if not isinstance(name, string_types):
      raise ValueError('name must be a binary name, given {} of type {}'.format(name, type(name)))
    self.validate()
    return self._validated_executable(name)

  def validate(self):
    """Validates this distribution against its configured constraints.

    Raises Distribution.Error if this distribution is not valid according to the configured
    constraints.
    """
    if self._validated_binaries:
      return

    with self._valid_executable('java') as java:
      if self._minimum_version:
        version = self._get_version(java)
        if version < self._minimum_version:
          raise self.Error('The java distribution at {} is too old; expecting at least {} and'
                           ' got {}'.format(java, self._minimum_version, version))
      if self._maximum_version:
        version = self._get_version(java)
        if version > self._maximum_version:
          raise self.Error('The java distribution at {} is too new; expecting no older than'
                           ' {} and got {}'.format(java, self._maximum_version, version))

    # We might be a JDK discovered by the embedded jre `java` executable.
    # If so reset the bin path to the true JDK home dir for full access to all binaries.
    self._bin_path = os.path.join(self.home, 'bin')

    try:
      self._validated_executable('javac')  # Calling purely for the check and cache side effects
      self._is_jdk = True
    except self.Error:
      if self._jdk:
        raise

  def _get_version(self, java):
    if not self._version:
      self._version = self._parse_java_version('java.version',
                                               self._get_system_properties(java)['java.version'])
    return self._version

  def _get_system_properties(self, java):
    if not self._system_properties:
      with temporary_dir() as classpath:
        with open(os.path.join(classpath, 'SystemProperties.class'), 'w+') as fp:
          fp.write(pkgutil.get_data(__name__, 'SystemProperties.class'))
        cmd = [java, '-cp', classpath, 'SystemProperties']
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()
        if process.returncode != 0:
          raise self.Error('Failed to determine java system properties for {} with {} - exit code'
                           ' {}: {}'.format(java, ' '.join(cmd), process.returncode, stderr))

      props = {}
      for line in stdout.split(os.linesep):
        key, _, val = line.partition('=')
        props[key] = val
      self._system_properties = props

    return self._system_properties

  def _validate_executable(self, name):
    def bin_paths():
      yield self._bin_path
      if self._is_jdk:
        yield os.path.join(self.home, 'jre', 'bin')

    for bin_path in bin_paths():
      exe = os.path.join(bin_path, name)
      if self._is_executable(exe):
        return exe
    raise self.Error('Failed to locate the {} executable, {} does not appear to be a'
                     ' valid {} distribution'.format(name, self, 'JDK' if self._jdk else 'JRE'))

  def _validated_executable(self, name):
    exe = self._validated_binaries.get(name)
    if not exe:
      exe = self._validate_executable(name)
      self._validated_binaries[name] = exe
    return exe

  @contextmanager
  def _valid_executable(self, name):
    exe = self._validate_executable(name)
    yield exe
    self._validated_binaries[name] = exe

  def __repr__(self):
    return ('Distribution({!r}, minimum_version={!r}, maximum_version={!r} jdk={!r})'.format(
            self._bin_path, self._minimum_version, self._maximum_version, self._jdk))
