# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import subprocess

from pants.fs.archive import ZIP
from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


# JVM classes can have non-ASCII names. Make sure we don't assume ASCII.


class BundleIntegrationTest(PantsRunIntegrationTest):
  def test_bundle_of_nonascii_classes(self):
    # TODO(John Sirois): We need a zip here to suck in external library classpath elements
    # pointed to by symlinks in the run_pants ephemeral tmpdir.  Switch run_pants to be a
    # contextmanager that yields its results while the tmpdir chroot is still active and change
    # this test back to using an un-archived bundle.
    pants_run = self.run_pants(['goal', 'bundle', '--bundle-archive=zip',
                                'src/java/com/pants/testproject/unicode/main'])
    self.assertEquals(pants_run.returncode, self.PANTS_SUCCESS_CODE,
                      "goal bundle expected success, got {0}\n"
                      "got stderr:\n{1}\n"
                      "got stdout:\n{2}\n".format(pants_run.returncode,
                                                  pants_run.stderr_data,
                                                  pants_run.stdout_data))

    with temporary_dir() as chroot:
      ZIP.extract('dist/unicode-testproject.zip', chroot)
      java_run = subprocess.Popen(['java', '-jar', 'unicode-testproject.jar'],
                                  stdout=subprocess.PIPE,
                                  cwd=chroot)
      stdout, _ = java_run.communicate()
      java_returncode = java_run.returncode
      self.assertEquals(java_returncode, 0)
      self.assertTrue("Have a nice day!" in stdout)
      self.assertTrue("shapeless success" in stdout)
