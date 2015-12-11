# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
from subprocess import PIPE, Popen
from textwrap import dedent

from pants.fs.archive import ZIP
from pants.util.contextutil import temporary_dir


class JvmPlatformIntegrationMixin(object):
  """Mixin providing lots of JvmPlatform-related integration tests to java compilers (eg, zinc)."""

  def get_pants_compile_args(self):
    """List of arguments to pants that determine what compiler to use.

    The compiling task must be the last argument (eg, compile.zinc).
    """
    raise NotImplementedError

  def determine_version(self, path):
    """Given the filepath to a class file, invokes the 'file' commandline to find its java version.

    :param str path: filepath (eg, tempdir/Foo.class)
    :return: A java version string (eg, '1.6').
    """
    # Map of target version numbers to their equivalent class file versions, which are different.
    version_map = {
      '50.0': '1.6',
      '51.0': '1.7',
      '52.0': '1.8',
    }
    p = Popen(['file', path], stdout=PIPE, stderr=PIPE)
    out, err = p.communicate()
    self.assertEqual(0, p.returncode, 'Failed to run file on {}.'.format(path))
    match = re.search(r'version (\d+[.]\d+)', out)
    self.assertTrue(match is not None, 'Could not determine version for {}'.format(path))
    return version_map[match.group(1)]

  def _get_jar_class_versions(self, jarname):
    path = os.path.join('dist', jarname)
    self.assertTrue(os.path.exists(path), '{} does not exist.'.format(path))

    class_to_version = {}
    with temporary_dir() as tempdir:
      ZIP.extract(path, tempdir, filter_func=lambda f: f.endswith('.class'))
      for root, dirs, files in os.walk(tempdir):
        for name in files:
          path = os.path.abspath(os.path.join(root, name))
          class_to_version[os.path.relpath(path, tempdir)] = self.determine_version(path)
    return class_to_version

  def _get_compiled_class_versions(self, spec, more_args=None):
    more_args = more_args or []
    jar_name = os.path.basename(spec)
    while jar_name.endswith(':'):
      jar_name = jar_name[:-1]
    if ':' in jar_name:
      jar_name = jar_name[jar_name.find(':') + 1:]
    with temporary_dir() as cache_dir:
      config = {'cache.compile.zinc': {'write_to': [cache_dir]}}
      with self.temporary_workdir() as workdir:
        pants_run = self.run_pants_with_workdir(
          ['binary'] + self.get_pants_compile_args()
          + ['compile.checkstyle', '--skip', spec]
          + more_args,
          workdir, config)
        self.assert_success(pants_run)
        return self._get_jar_class_versions('{}.jar'.format(jar_name))

  def assert_class_versions(self, expected, received):
    def format_dict(d):
      return ''.join('\n    {} = {}'.format(key, val) for key, val in sorted(d.items()))
    self.assertEqual(expected, received,
                     'Compiled class versions differed.\n  expected: {}\n  received: {}'
                     .format(format_dict(expected), format_dict(received)))

  def test_compile_java6(self):
    target_spec = 'testprojects/src/java/org/pantsbuild/testproject/targetlevels/java6'
    self.assert_class_versions({
      'org/pantsbuild/testproject/targetlevels/java6/Six.class': '1.6',
    }, self._get_compiled_class_versions(target_spec))

  def test_compile_java7(self):
    target_spec = 'testprojects/src/java/org/pantsbuild/testproject/targetlevels/java7'
    self.assert_class_versions({
      'org/pantsbuild/testproject/targetlevels/java7/Seven.class': '1.7',
    }, self._get_compiled_class_versions(target_spec))

  def test_compile_java7on6(self):
    target_spec = 'testprojects/src/java/org/pantsbuild/testproject/targetlevels/java7on6'
    self.assert_class_versions({
      'org/pantsbuild/testproject/targetlevels/java7on6/SevenOnSix.class': '1.7',
      'org/pantsbuild/testproject/targetlevels/java6/Six.class': '1.6',
    }, self._get_compiled_class_versions(target_spec))

  def test_compile_target_coercion(self):
    target_spec = 'testprojects/src/java/org/pantsbuild/testproject/targetlevels/unspecified'
    self.assert_class_versions({
      'org/pantsbuild/testproject/targetlevels/unspecified/Unspecified.class': '1.7',
      'org/pantsbuild/testproject/targetlevels/unspecified/Six.class': '1.6',
    }, self._get_compiled_class_versions(target_spec, more_args=[
      '--jvm-platform-validate-check=warn',
      '--jvm-platform-default-platform=java7',
    ]))

  def _test_compile(self, target_level, class_name, source_contents, platform_args=None):
    with temporary_dir(root_dir=os.path.abspath('.')) as tmpdir:
      with open(os.path.join(tmpdir, 'BUILD'), 'w') as f:
        f.write(dedent('''
        java_library(name='{target_name}',
          sources=['{class_name}.java'],
          platform='{target_level}',
        )
        '''.format(target_name=os.path.basename(tmpdir),
                   class_name=class_name,
                   target_level=target_level)))
      with open(os.path.join(tmpdir, '{}.java'.format(class_name)), 'w') as f:
        f.write(source_contents)
      platforms = str({
        str(target_level): {
          'source': str(target_level),
          'target': str(target_level),
          'args': platform_args or [],
        }
      })
      command = []
      command.extend(['--jvm-platform-platforms={}'.format(platforms),
                      '--jvm-platform-default-platform={}'.format(target_level)])
      command.extend(self.get_pants_compile_args())
      command.extend([tmpdir])

      pants_run = self.run_pants(command)
      return pants_run

  def test_compile_diamond_operator_java7_works(self):
    pants_run = self._test_compile('1.7', 'Diamond', dedent('''
      public class Diamond<T> {
        public static void main(String[] args) {
          Diamond<String> diamond = new Diamond<>();
        }
      }
    '''))
    self.assert_success(pants_run)

  def test_compile_diamond_operator_java6_fails(self):
    pants_run = self._test_compile('1.6', 'Diamond', dedent('''
      public class Diamond<T> {
        public static void main(String[] args) {
          Diamond<String> diamond = new Diamond<>();
        }
      }
    '''))
    self.assert_failure(pants_run)

  def test_compile_with_javac_args(self):
    pants_run = self._test_compile('1.7', 'LintyDiamond', dedent('''
      public class LintyDiamond<T> {
        public static void main(String[] args) {
          LintyDiamond<String> diamond = new LintyDiamond<>();
        }
      }
    '''), platform_args=['-C-Xlint:cast'])
    self.assert_success(pants_run)

  def test_compile_stale_platform_settings(self):
    # Tests that targets are properly re-compiled when their source/target levels change.
    with temporary_dir(root_dir=os.path.abspath('.')) as tmpdir:
      with open(os.path.join(tmpdir, 'BUILD'), 'w') as f:
        f.write(dedent('''
        java_library(name='diamond',
          sources=['Diamond.java'],
        )
        '''))
      with open(os.path.join(tmpdir, 'Diamond.java'), 'w') as f:
        f.write(dedent('''
          public class Diamond<T> {
            public static void main(String[] args) {
              // The diamond operator <> for generics was introduced in jdk7.
              Diamond<String> shinyDiamond = new Diamond<>();
            }
          }
        '''))
      platforms = {
        'java6': {'source': '6'},
        'java7': {'source': '7'},
      }

      # We run these all in the same working directory, because we're testing caching behavior.
      with self.temporary_workdir() as workdir:

        def compile_diamond(platform):
          return self.run_pants_with_workdir(['--jvm-platform-platforms={}'.format(platforms),
                                              '--jvm-platform-default-platform={}'.format(platform),
                                              '-ldebug',
                                              'compile'] + self.get_pants_compile_args() +
                                              ['{}:diamond'.format(tmpdir)], workdir=workdir)

        # We shouldn't be able to compile this with -source=6.
        self.assert_failure(compile_diamond('java6'), 'Diamond.java was compiled successfully with '
                                                      'java6 starting from a fresh workdir, but '
                                                      'that should not be possible.')

        # We should be able to compile this with -source=7.
        self.assert_success(compile_diamond('java7'), 'Diamond.java failed to compile in java7, '
                                                      'which it should be able to.')

        # We still shouldn't be able to compile this with -source=6. If the below passes, it means
        #  that we saved the cached run from java7 and didn't recompile, which is an error.
        self.assert_failure(compile_diamond('java6'), 'Diamond.java erroneously compiled in java6,'
                                                      ' which means that either compilation was'
                                                      ' skipped due to bad fingerprinting/caching,'
                                                      ' or the compiler failed to clean up the'
                                                      ' previous class from the java7'
                                                      ' compile.')
