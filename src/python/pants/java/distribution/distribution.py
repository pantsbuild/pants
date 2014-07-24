# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import pkgutil
import subprocess
from contextlib import contextmanager

from twitter.common import log
from twitter.common.lang import Compatibility

from pants.base.revision import Revision
from pants.util.contextutil import temporary_dir


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
      for dist in cls._CACHE.values():
        if minimum_version and dist.version < minimum_version:
          continue
        if maximum_version and dist.version > maximum_version:
          continue
        if jdk and not dist.jdk:
          continue
        return dist

    key = (minimum_version, jdk)
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
        dist = cls(path, minimum_version=minimum_version, maximum_version=maximum_version, jdk=jdk)
        dist.validate()
        log.debug('Located %s for constraints: minimum_version'
                  ' %s, maximum_version %s, jdk %s' % (dist, minimum_version, maximum_version, jdk))
        return dist
      except (ValueError, cls.Error):
        pass

    raise cls.Error('Failed to locate a %s distribution with minimum_version %s, maximum_version %s'
                    % ('JDK' if jdk else 'JRE', minimum_version, maximum_version))

  @staticmethod
  def _parse_java_version(name, version):
    # Java version strings have been well defined since release 1.3.1 as defined here:
    #  http://www.oracle.com/technetwork/java/javase/versioning-naming-139433.html
    # These version strings comply with semver except that the traditional pre-release semver
    # slot (the 4th) can be delimited by an _ in the case of update releases of the jdk.
    # We accomodate that difference here.
    if isinstance(version, Compatibility.string):
      version = Revision.semver(version.replace('_', '-'))
    if version and not isinstance(version, Revision):
      raise ValueError('%s must be a string or a Revision object, given: %s' % (name, version))
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
      raise ValueError('The specified distribution path is invalid: %s' % bin_path)
    self._bin_path = bin_path

    self._minimum_version = self._parse_java_version("minimum_version", minimum_version)
    self._maximum_version = self._parse_java_version("maximum_version", maximum_version)

    self._jdk = jdk

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

  @property
  def home(self):
    """Returns the distribution JAVA_HOME."""
    return self._get_system_properties(self.java)['java.home']

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
    """
    if not isinstance(name, Compatibility.string):
      raise ValueError('name must be a binary name, given %s of type %s' % (name, type(name)))
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
          raise self.Error('The java distribution at %s is too old; expecting at least %s and'
                           ' got %s' % (java, self._minimum_version, version))
      if self._maximum_version:
        version = self._get_version(java)
        if version > self._maximum_version:
          raise self.Error('The java distribution at %s is too new; expecting no older than'
                           ' %s and got %s' % (java, self._maximum_version, version))

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
          raise self.Error('Failed to determine java system properties for %s with %s - exit code'
                           ' %d: %s' % (java, ' '.join(cmd), process.returncode, stderr))

      props = {}
      for line in stdout.split(os.linesep):
        key, _, val = line.partition('=')
        props[key] = val
      self._system_properties = props

    return self._system_properties

  def _validate_executable(self, name):
    exe = os.path.join(self._bin_path, name)
    if not self._is_executable(exe):
      raise self.Error('Failed to locate the %s executable, %s does not appear to be a'
                       ' valid %s distribution' % (name, self, 'JDK' if self._jdk else 'JRE'))
    return exe

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
    return ('Distribution(%r, minimum_version=%r, maximum_version=%r jdk=%r)'
           % (self._bin_path, self._minimum_version, self._maximum_version, self._jdk))
