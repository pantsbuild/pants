# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import itertools
import logging
import os
import pkgutil
import plistlib
import subprocess
from abc import abstractproperty
from collections import namedtuple
from contextlib import contextmanager

from six import string_types

from pants.base.revision import Revision
from pants.java.util import execute_java, execute_java_async
from pants.subsystem.subsystem import Subsystem
from pants.util.contextutil import temporary_dir
from pants.util.memo import memoized_method, memoized_property
from pants.util.meta import AbstractClass
from pants.util.osutil import OS_ALIASES, normalize_os_name


logger = logging.getLogger(__name__)


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


class Distribution(object):
  """Represents a java distribution - either a JRE or a JDK installed on the local system.

  In particular provides access to the distribution's binaries; ie: java while ensuring basic
  constraints are met.  For example a minimum version can be specified if you know need to compile
  source code or run bytecode that exercise features only available in that version forward.

  :API: public

  TODO(John Sirois): This class has a broken API, its not reasonably useful with no methods exposed.
  Expose reasonable methods: https://github.com/pantsbuild/pants/issues/3263
  """

  class Error(Exception):
    """Indicates an invalid java distribution."""

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

    self._minimum_version = _parse_java_version("minimum_version", minimum_version)
    self._maximum_version = _parse_java_version("maximum_version", maximum_version)
    self._jdk = jdk
    self._is_jdk = False
    self._system_properties = None
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
  def real_home(self):
    """Real path to the distribution java.home (resolving links)."""
    return os.path.realpath(self.home)

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
    except self.Error as e:
      if self._jdk:
        logger.debug('Failed to validate javac executable. Please check you have a JDK '
                      'installed. Original error: {}'.format(e))
        raise

  def execute_java(self, *args, **kwargs):
    return execute_java(*args, distribution=self, **kwargs)

  def execute_java_async(self, *args, **kwargs):
    return execute_java_async(*args, distribution=self, **kwargs)

  @memoized_method
  def _get_version(self, java):
    return _parse_java_version('java.version', self._get_system_properties(java)['java.version'])

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


class _DistributionEnvironment(AbstractClass):
  class Location(namedtuple('Location', ['home_path', 'bin_path'])):
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

  @abstractproperty
  def jvm_locations(self):
    """Return the jvm locations discovered in this environment.

    :returns: An iterator over all discovered jvm locations.
    :rtype: iterator of :class:`DistributionEnvironment.Location`
    """


class _EnvVarEnvironment(_DistributionEnvironment):
  @property
  def jvm_locations(self):
    def env_home(home_env_var):
      home = os.environ.get(home_env_var)
      return self.Location.from_home(home) if home else None

    jdk_home = env_home('JDK_HOME')
    if jdk_home:
      yield jdk_home

    java_home = env_home('JAVA_HOME')
    if java_home:
      yield java_home

    search_path = os.environ.get('PATH')
    if search_path:
      for bin_path in search_path.strip().split(os.pathsep):
        yield self.Location.from_bin(bin_path)


class _OSXEnvironment(_DistributionEnvironment):
  _OSX_JAVA_HOME_EXE = '/usr/libexec/java_home'

  @classmethod
  def standard(cls):
    return cls(cls._OSX_JAVA_HOME_EXE)

  def __init__(self, osx_java_home_exe):
    self._osx_java_home_exe = osx_java_home_exe

  @property
  def jvm_locations(self):
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
    if os.path.exists(self._osx_java_home_exe):
      try:
        plist = subprocess.check_output([self._osx_java_home_exe, '--failfast', '--xml'])
        for distribution in plistlib.readPlistFromString(plist):
          home = distribution['JVMHomePath']
          yield self.Location.from_home(home)
      except subprocess.CalledProcessError:
        pass


class _LinuxEnvironment(_DistributionEnvironment):
  # The `/usr/lib/jvm` dir is a common target of packages built for redhat and debian as well as
  # other more exotic distributions.  SUSE uses lib64
  _STANDARD_JAVA_DIST_DIRS = ('/usr/lib/jvm', '/usr/lib64/jvm')

  @classmethod
  def standard(cls):
    return cls(*cls._STANDARD_JAVA_DIST_DIRS)

  def __init__(self, *java_dist_dirs):
    if len(java_dist_dirs) == 0:
      raise ValueError('Expected at least 1 java dist dir.')
    self._java_dist_dirs = java_dist_dirs

  @property
  def jvm_locations(self):
    for java_dist_dir in self._java_dist_dirs:
      if os.path.isdir(java_dist_dir):
        for path in os.listdir(java_dist_dir):
          home = os.path.join(java_dist_dir, path)
          if os.path.isdir(home):
            yield self.Location.from_home(home)


class _ExplicitEnvironment(_DistributionEnvironment):
  def __init__(self, *homes):
    self._homes = homes

  @property
  def jvm_locations(self):
    for home in self._homes:
      yield self.Location.from_home(home)


class _UnknownEnvironment(_DistributionEnvironment):
  def __init__(self, *possible_environments):
    super(_DistributionEnvironment, self).__init__()
    if len(possible_environments) < 2:
      raise ValueError('At least two possible environments must be supplied.')
    self._possible_environments = possible_environments

  @property
  def jvm_locations(self):
    return itertools.chain(*(pe.jvm_locations for pe in self._possible_environments))


class _Locator(object):
  class Error(Distribution.Error):
    """Error locating a java distribution."""

  def __init__(self, distribution_environment, minimum_version=None, maximum_version=None):
    self._cache = {}
    self._distribution_environment = distribution_environment
    self._minimum_version = minimum_version
    self._maximum_version = maximum_version

  def _scan_constraint_match(self, minimum_version, maximum_version, jdk):
    """Finds a cached version matching the specified constraints

    :param Revision minimum_version: minimum jvm version to look for (eg, 1.7).
    :param Revision maximum_version: maximum jvm version to look for (eg, 1.7.9999).
    :param bool jdk: whether the found java distribution is required to have a jdk.
    :return: the Distribution, or None if no matching distribution is in the cache.
    :rtype: :class:`pants.java.distribution.Distribution`
    """

    for dist in self._cache.values():
      if minimum_version and dist.version < minimum_version:
        continue
      if maximum_version and dist.version > maximum_version:
        continue
      if jdk and not dist.jdk:
        continue
      return dist

  def locate(self, minimum_version=None, maximum_version=None, jdk=False):
    """Finds a java distribution that meets the given constraints and returns it.

    First looks for a cached version that was previously located, otherwise calls locate().
    :param minimum_version: minimum jvm version to look for (eg, 1.7).
                            The stricter of this and `--jvm-distributions-minimum-version` is used.
    :param maximum_version: maximum jvm version to look for (eg, 1.7.9999).
                            The stricter of this and `--jvm-distributions-maximum-version` is used.
    :param bool jdk: whether the found java distribution is required to have a jdk.
    :return: the Distribution.
    :rtype: :class:`Distribution`
    :raises: :class:`Distribution.Error` if no suitable java distribution could be found.
    """

    def _get_stricter_version(a, b, name, stricter):
      version_a = _parse_java_version(name, a)
      version_b = _parse_java_version(name, b)
      if version_a is None:
        return version_b
      if version_b is None:
        return version_a
      return stricter(version_a, version_b)

    # take the tighter constraint of method args and subsystem options
    minimum_version = _get_stricter_version(minimum_version,
                                            self._minimum_version,
                                            "minimum_version",
                                            max)
    maximum_version = _get_stricter_version(maximum_version,
                                            self._maximum_version,
                                            "maximum_version",
                                            min)

    key = (minimum_version, maximum_version, jdk)
    dist = self._cache.get(key)
    if not dist:
      dist = self._scan_constraint_match(minimum_version, maximum_version, jdk)
      if not dist:
        dist = self._locate(minimum_version=minimum_version,
                            maximum_version=maximum_version,
                            jdk=jdk)
      self._cache[key] = dist
    return dist

  def _locate(self, minimum_version=None, maximum_version=None, jdk=False):
    """Finds a java distribution that meets any given constraints and returns it.

    :param minimum_version: minimum jvm version to look for (eg, 1.7).
    :param maximum_version: maximum jvm version to look for (eg, 1.7.9999).
    :param bool jdk: whether the found java distribution is required to have a jdk.
    :return: the located Distribution.
    :rtype: :class:`Distribution`
    :raises: :class:`Distribution.Error` if no suitable java distribution could be found.
    """
    for location in itertools.chain(self._distribution_environment.jvm_locations):
      try:
        dist = Distribution(home_path=location.home_path,
                            bin_path=location.bin_path,
                            minimum_version=minimum_version,
                            maximum_version=maximum_version,
                            jdk=jdk)
        dist.validate()
        logger.debug('Located {} for constraints: minimum_version {}, maximum_version {}, jdk {}'
                     .format(dist, minimum_version, maximum_version, jdk))
        return dist
      except (ValueError, Distribution.Error) as e:
        logger.debug('{} is not a valid distribution because: {}'
                     .format(location.home_path, str(e)))
        pass

    if (minimum_version is not None
        and maximum_version is not None
        and maximum_version < minimum_version):
      error_format = ('Pants configuration/options led to impossible constraints for {} '
                      'distribution: minimum_version {}, maximum_version {}')
    else:
      error_format = ('Failed to locate a {} distribution with minimum_version {}, '
                      'maximum_version {}')
    raise self.Error(error_format.format('JDK' if jdk else 'JRE', minimum_version, maximum_version))


class DistributionLocator(Subsystem):
  """Subsystem that knows how to look up a java Distribution.

  Distributions are searched for in the following order by default:

  1. Paths listed for this operating system in the `--jvm-distributions-paths` map.
  2. JDK_HOME/JAVA_HOME
  3. PATH
  4. Likely locations on the file system such as `/usr/lib/jvm` on Linux machines.

  :API: public
  """

  class Error(Distribution.Error):
    """Error locating a java distribution.

    :API: public
    """

  @classmethod
  @memoized_method
  def _locator(cls):
    environment = _UnknownEnvironment(_EnvVarEnvironment(),
                                      _LinuxEnvironment.standard(),
                                      _OSXEnvironment.standard())
    return cls.global_instance()._create_locator(environment)

  @classmethod
  def cached(cls, minimum_version=None, maximum_version=None, jdk=False):
    """Finds a java distribution that meets the given constraints and returns it.

    :API: public

    First looks for a cached version that was previously located, otherwise calls locate().
    :param minimum_version: minimum jvm version to look for (eg, 1.7).
                            The stricter of this and `--jvm-distributions-minimum-version` is used.
    :param maximum_version: maximum jvm version to look for (eg, 1.7.9999).
                            The stricter of this and `--jvm-distributions-maximum-version` is used.
    :param bool jdk: whether the found java distribution is required to have a jdk.
    :return: the Distribution.
    :rtype: :class:`Distribution`
    :raises: :class:`Distribution.Error` if no suitable java distribution could be found.
    """
    try:
      return cls._locator().locate(minimum_version=minimum_version,
                                   maximum_version=maximum_version,
                                   jdk=jdk)
    except _Locator.Error as e:
      raise cls.Error('Problem locating a java distribution: {}'.format(e))

  options_scope = 'jvm-distributions'

  @classmethod
  def register_options(cls, register):
    super(DistributionLocator, cls).register_options(register)
    human_readable_os_aliases = ', '.join('{}: [{}]'.format(str(key), ', '.join(sorted(val)))
                                          for key, val in OS_ALIASES.items())
    register('--paths', advanced=True, type=dict,
             help='Map of os names to lists of paths to jdks. These paths will be searched before '
                  'everything else (before the JDK_HOME, JAVA_HOME, PATH environment variables) '
                  'when locating a jvm to use. The same OS can be specified via several different '
                  'aliases, according to this map: {}'.format(human_readable_os_aliases))
    register('--minimum-version', advanced=True, help='Minimum version of the JVM pants will use')
    register('--maximum-version', advanced=True, help='Maximum version of the JVM pants will use')

  def all_jdk_paths(self):
    """Get all explicitly configured JDK paths.

    :return: mapping of os name -> list of jdk_paths
    :rtype: dict of string -> list of string
    """
    return self._normalized_jdk_paths

  @memoized_property
  def _normalized_jdk_paths(self):
    normalized = {}
    jdk_paths = self.get_options().paths or {}
    for name, paths in sorted(jdk_paths.items()):
      rename = normalize_os_name(name)
      if rename in normalized:
        logger.warning('Multiple OS names alias to "{}"; combining results.'.format(rename))
        normalized[rename].extend(paths)
      else:
        normalized[rename] = paths
    return normalized

  def _get_explicit_jdk_paths(self):
    if not self._normalized_jdk_paths:
      return ()
    os_name = normalize_os_name(os.uname()[0].lower())
    if os_name not in self._normalized_jdk_paths:
      logger.warning('--jvm-distributions-paths was specified, but has no entry for "{}".'
                     .format(os_name))
    return self._normalized_jdk_paths.get(os_name, ())

  def _create_locator(self, distribution_environment):
    homes = self._get_explicit_jdk_paths()
    environment = _UnknownEnvironment(_ExplicitEnvironment(*homes), distribution_environment)
    return _Locator(environment,
                    self.get_options().minimum_version,
                    self.get_options().maximum_version)

  # Exposed for tests.
  def _reset(self):
    self._locator.clear()
    self._normalized_jdk_paths.clear()
