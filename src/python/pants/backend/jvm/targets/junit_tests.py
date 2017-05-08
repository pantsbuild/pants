# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.subsystems.junit import JUnit
from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField


class DeprecatedJavaTestsAlias(JvmTarget):
  pass


# Subclasses DeprecatedJavaTestsAlias so that checks for
# isinstance(pants.backend.jvm.targets.java_tests.JavaTests) will
# return true for these instances during the migration.
#
# To migrate such code, change all BUILD files to use junit_tests instead of java_tests,
# to get rid of deprecation warnings for the java_tests BUILD file aliases.
# Then change the checks to isinstance(pants.backend.jvm.targets.junit_tests.JUnitTests),
# to get rid of the module-level deprecation warning for java_tests.
class JUnitTests(DeprecatedJavaTestsAlias):
  """JUnit tests.

  :API: public
  """

  java_test_globs = ('*Test.java',)
  scala_test_globs = ('*Test.scala', '*Spec.scala')

  default_sources_globs = java_test_globs + scala_test_globs


  CONCURRENCY_SERIAL = 'SERIAL'
  CONCURRENCY_PARALLEL_CLASSES = 'PARALLEL_CLASSES'
  CONCURRENCY_PARALLEL_METHODS = 'PARALLEL_METHODS'
  CONCURRENCY_PARALLEL_CLASSES_AND_METHODS = 'PARALLEL_CLASSES_AND_METHODS'
  VALID_CONCURRENCY_OPTS = [CONCURRENCY_SERIAL,
                            CONCURRENCY_PARALLEL_CLASSES,
                            CONCURRENCY_PARALLEL_METHODS,
                            CONCURRENCY_PARALLEL_CLASSES_AND_METHODS]

  @classmethod
  def subsystems(cls):
    return super(JUnitTests, cls).subsystems() + (JUnit,)

  def __init__(self, cwd=None, test_platform=None, payload=None, timeout=None,
               extra_jvm_options=None, extra_env_vars=None, concurrency=None,
               threads=None, **kwargs):
    """
    :param str cwd: working directory (relative to the build root) for the tests under this
      target. If unspecified (None), the working directory will be controlled by junit_run's --cwd.
    :param str test_platform: The name of the platform (defined under the jvm-platform subsystem) to
      use for running tests (that is, a key into the --jvm-platform-platforms dictionary). If
      unspecified, the platform will default to the same one used for compilation.
    :param int timeout: A timeout (in seconds) which covers the total runtime of all tests in this
      target. Only applied if `--test-junit-timeouts` is set to True.
    :param list extra_jvm_options: A list of key value pairs of jvm options to use when running the
      tests. Example: ['-Dexample.property=1'] If unspecified, no extra jvm options will be added.
    :param dict extra_env_vars: A map of environment variables to set when running the tests, e.g.
      { 'FOOBAR': 12 }. Using `None` as the value will cause the variable to be unset.
    :param string concurrency: One of 'SERIAL', 'PARALLEL_CLASSES', 'PARALLEL_METHODS',
      or 'PARALLEL_CLASSES_AND_METHODS'.  Overrides the setting of --test-junit-default-concurrency.
    :param int threads: Use the specified number of threads when running the test. Overrides
      the setting of --test-junit-parallel-threads.
    """

    payload = payload or Payload()

    if extra_env_vars is None:
      extra_env_vars = {}
    for key, value in extra_env_vars.items():
      if value is not None:
        extra_env_vars[key] = str(value)

    payload.add_fields({
      'test_platform': PrimitiveField(test_platform),
      # TODO(zundel): Do extra_jvm_options and extra_env_vars really need to be fingerprinted?
      'extra_jvm_options': PrimitiveField(tuple(extra_jvm_options or ())),
      'extra_env_vars': PrimitiveField(tuple(extra_env_vars.items())),
    })
    super(JUnitTests, self).__init__(payload=payload, **kwargs)

    # These parameters don't need to go into the fingerprint:
    self._concurrency = concurrency
    self._cwd = cwd
    self._threads = None
    self._timeout = timeout

    try:
      if threads is not None:
        self._threads = int(threads)
    except ValueError:
      raise TargetDefinitionException(self,
                                      "The value for 'threads' must be an integer, got " + threads)
    if concurrency and concurrency not in self.VALID_CONCURRENCY_OPTS:
      raise TargetDefinitionException(self,
                                      "The value for 'concurrency' must be one of "
                                      + repr(self.VALID_CONCURRENCY_OPTS) + " got: " + concurrency)

    # TODO(John Sirois): These could be scala, clojure, etc.  'jvm' and 'tests' are the only truly
    # applicable labels - fixup the 'java' misnomer.
    self.add_labels('java', 'tests')

  @classmethod
  def compute_dependency_specs(cls, kwargs=None, payload=None):
    for spec in super(JUnitTests, cls).compute_dependency_specs(kwargs, payload):
      yield spec

    for spec in JUnit.global_instance().injectables_specs_for_key('library'):
      yield spec

  @property
  def test_platform(self):
    if self.payload.test_platform:
      return JvmPlatform.global_instance().get_platform_by_name(self.payload.test_platform)
    return self.platform

  @property
  def concurrency(self):
    return self._concurrency

  @property
  def cwd(self):
    return self._cwd

  @property
  def threads(self):
    return self._threads

  @property
  def timeout(self):
    return self._timeout
