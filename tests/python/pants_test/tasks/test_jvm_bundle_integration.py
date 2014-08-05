# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import subprocess

from pants.fs.archive import ZIP
from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class BundleIntegrationTest(PantsRunIntegrationTest):

  def _exec_bundle(self, target, bundle_name):
    ''' Creates the bundle with pants, then does java -jar {bundle_name}.jar to execute the bundle.
    :param target: target name to compile
    :param bundle_name: resulting bundle filename (minus .jar extension)
    :return: stdout as a string on success, raises an Exception on error
    '''
    pants_run = self.run_pants(['goal', 'bundle', '--bundle-archive=zip', target])
    self.assertEquals(pants_run.returncode, self.PANTS_SUCCESS_CODE,
                      "goal bundle expected success, got {0}\n"
                      "got stderr:\n{1}\n"
                      "got stdout:\n{2}\n".format(pants_run.returncode,
                                                  pants_run.stderr_data,
                                                  pants_run.stdout_data))

    # TODO(John Sirois): We need a zip here to suck in external library classpath elements
    # pointed to by symlinks in the run_pants ephemeral tmpdir.  Switch run_pants to be a
    # contextmanager that yields its results while the tmpdir workdir is still active and change
    # this test back to using an un-archived bundle.
    with temporary_dir() as workdir:
      ZIP.extract('dist/{bundle_name}.zip'.format(bundle_name=bundle_name), workdir)
      java_run = subprocess.Popen(['java',
                                   '-jar',
                                   '{bundle_name}.jar'.format(bundle_name=bundle_name)],
                                  stdout=subprocess.PIPE,
                                  cwd=workdir)

      stdout, _ = java_run.communicate()
    java_returncode = java_run.returncode
    self.assertEquals(java_returncode, 0)
    return stdout

  def test_bundle_of_nonascii_classes(self):
    """JVM classes can have non-ASCII names. Make sure we don't assume ASCII."""

    stdout = self._exec_bundle('testprojects/src/java/com/pants/testproject/unicode/main', 'unicode-testproject')
    self.assertIn("Have a nice day!", stdout)
    self.assertIn("shapeless success", stdout)

  def test_bundle_colliding_resources(self):
    """Tests that the proper resource is bundled with each of these bundled targets when
    each project has a different resource with the same path.
    """
    for name in ['a', 'b', 'c']:
      target = ('testprojects/maven_layout/resource_collision/example_{name}/'
                'src/main/java/com/pants/duplicateres/example{name}/'
                .format(name=name))
      bundle_name='example{proj}'.format(proj=name)
      stdout = self._exec_bundle(target, bundle_name)
      self.assertEquals(stdout, 'Hello world!: resource from example {name}\n'.format(name=name))

