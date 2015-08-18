# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import pkgutil
import plistlib
import subprocess
from collections import namedtuple
from contextlib import contextmanager

from six import string_types

from pants.backend.jvm.subsystems.jvm import JVM
from pants.base.revision import Revision
from pants.subsystem.subsystem import SubsystemError
from pants.util.contextutil import temporary_dir


logger = logging.getLogger(__name__)


# TODO(gmalmquist): Make Distribution a subsystem that depends on JVM.
# (see discussion on https://rbcommons.com/s/twitter/r/2657/)
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

  class _Location(namedtuple('Location', ['home_path', 'bin_path'])):
    """Represents the location of a java distribution."""
    @classmethod
    def from_home(cls, home):
      """Creates a location given the JAVA_HOME directory.

      :param string home: The path of the JAVA_HOME directory.
      :returns: The java distribution location.
      """
      return cls(home_path=home, bin_path=None)

    @classmethod
    def from_bin(cls, bin_path):
      """Creates a location given the `java` executable parent directory.

      :param string bin_path: The parent path of the `java` executable.
      :returns: The java distribution location.
      """
      return cls(home_path=None, bin_path=bin_path)

  # The `/usr/lib/jvm` dir is a common target of packages built for redhat and debian as well as
  # other more exotic distributions.
  _JAVA_DIST_DIR = '/usr/lib/jvm'

  @classmethod
  def _linux_java_homes(cls):
    if os.path.isdir(cls._JAVA_DIST_DIR):
      for path in os.listdir(cls._JAVA_DIST_DIR):
        home = os.path.join(cls._JAVA_DIST_DIR, path)
        if os.path.isdir(home):
          yield cls._Location.from_home(home)

  _OSX_JAVA_HOME_EXE = '/usr/libexec/java_home'

  @classmethod
  def _osx_java_homes(cls):
    # OSX will have a java_home tool that can be used to locate a unix-compatible java home dir.
    #
    # See:
    #   https://developer.apple.com/library/mac/documentation/Darwin/Reference/ManPages/man1/java_home.1.html
    #
    # The `--xml` output looks like so:
    # <?xml version="1.0" encoding="UTF-8"?>
    # <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    #                        "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
    # <plist version="1.0">
    #   <array>
    #     <dict>
    #       ...
    #       <key>JVMHomePath</key>
    #       <string>/Library/Java/JavaVirtualMachines/jdk1.7.0_45.jdk/Contents/Home</string>
    #       ...
    #     </dict>
    #     ...
    #   </array>
    # </plist>
    if os.path.exists(cls._OSX_JAVA_HOME_EXE):
      try:
        plist = subprocess.check_output([cls._OSX_JAVA_HOME_EXE, '--failfast', '--xml'])
        for distribution in plistlib.readPlistFromString(plist):
          home = distribution['JVMHomePath']
          yield cls._Location.from_home(home)
      except subprocess.CalledProcessError:
        pass

  @classmethod
  def locate(cls, minimum_version=None, maximum_version=None, jdk=False):
    """Finds a java distribution that meets any given constraints and returns it.

    First looks in JDK_HOME and JAVA_HOME if defined falling back to a search on the PATH.
    Raises Distribution.Error if no suitable java distribution could be found.
    """
    def env_home(home_env_var):
      home = os.environ.get(home_env_var)
      return cls._Location.from_home(home) if home else None

    def search_path():
      try:
        for location in JVM.global_instance().get_jdk_paths():
          yield cls._Location.from_home(location)
      except SubsystemError:
        logger.warning('Java distribution requested before JVM subsystem initialized.')
        pass

      yield env_home('JDK_HOME')
      yield env_home('JAVA_HOME')

      for location in cls._linux_java_homes():
        yield location

      for location in cls._osx_java_homes():
        yield location

      search_path = os.environ.get('PATH')
      if search_path:
        for bin_path in search_path.strip().split(os.pathsep):
          yield cls._Location.from_bin(bin_path)

    for location in filter(None, search_path()):
      try:
        dist = cls(home_path=location.home_path,
                   bin_path=location.bin_path,
                   minimum_version=minimum_version,
                   maximum_version=maximum_version,
                   jdk=jdk)
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
    # We accommodate that difference here using lenient parsing.
    # We also accommodate specification versions, which just have major and minor
    # components; eg: `1.8`.  These are useful when specifying constraints a distribution must
    # satisfy; eg: to pick any 1.8 java distribution: '1.8' <= version <= '1.8.99'
    if isinstance(version, string_types):
      version = Revision.lenient(version)
    if version and not isinstance(version, Revision):
      raise ValueError('{} must be a string or a Revision object, given: {}'.format(name, version))
    return version

  @staticmethod
  def _is_executable(path):
    return os.path.isfile(path) and os.access(path, os.X_OK)

  def __init__(self, home_path=None, bin_path=None, minimum_version=None, maximum_version=None,
               jdk=False):
    """Creates a distribution wrapping the given `home_path` or `bin_path`.

    Only one of `home_path` or `bin_path` should be supplied.

    :param string home_path: the path to the java distribution's home dir
    :param string bin_path: the path to the java distribution's bin dir
    :param minimum_version: a modified semantic version string or else a Revision object
    :param maximum_version: a modified semantic version string or else a Revision object
    :param bool jdk: ``True`` to require the distribution be a JDK vs a JRE
    """
    if home_path and not os.path.isdir(home_path):
      raise ValueError('The specified java home path is invalid: {}'.format(home_path))
    if bin_path and not os.path.isdir(bin_path):
      raise ValueError('The specified binary path is invalid: {}'.format(bin_path))
    if not bool(home_path) ^ bool(bin_path):
      raise ValueError('Exactly one of home path or bin path should be supplied, given: '
                       'home_path={} bin_path={}'.format(home_path, bin_path))

    self._home = home_path
    self._bin_path = bin_path or (os.path.join(home_path, 'bin') if home_path else '/usr/bin')

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
    if not self._home:
      home = self._get_system_properties(self.java)['java.home']
      # The `jre/bin/java` executable in a JDK distribution will report `java.home` as the jre dir,
      # so we check for this and re-locate to the containing jdk dir when present.
      if os.path.basename(home) == 'jre':
        jdk_dir = os.path.dirname(home)
        if self._is_executable(os.path.join(jdk_dir, 'bin', 'javac')):
          home = jdk_dir
      self._home = home
    return self._home

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
