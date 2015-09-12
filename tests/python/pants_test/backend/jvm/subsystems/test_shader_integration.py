# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os
import subprocess
from contextlib import contextmanager

from pants.fs.archive import ZIP
from pants.java.distribution.distribution import DistributionLocator
from pants.java.executor import SubprocessExecutor
from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.subsystem.subsystem_util import subsystem_instance


class ShaderIntegrationTest(PantsRunIntegrationTest):

  def test_shader_project(self):
    """Test that the binary target at the ``shading_project`` can be built and run.

    Explicitly checks that the classes end up with the correct shaded fully qualified classnames.
    """
    shading_project = 'testprojects/src/java/org/pantsbuild/testproject/shading'
    self.assert_success(self.run_pants(['clean-all']))
    self.assert_success(self.run_pants(['binary', shading_project]))

    expected_classes = {
      # Explicitly excluded by a shading_exclude() rule.
      'org/pantsbuild/testproject/shadingdep/PleaseDoNotShadeMe.class',
      # Not matched by any rule, so stays the same.
      'org/pantsbuild/testproject/shading/Main.class',
      # Shaded with the target_id prefix, along with the default pants prefix.
      ('__shaded_by_pants__/org/pantsbuild/testproject/shadingdep/otherpackage/'
       'ShadeWithTargetId.class'),
      # Also shaded with the target_id prefix and default pants prefix, but for a different target
      # (so the target_id is different).
      ('__shaded_by_pants__/org/pantsbuild/testproject/shading/ShadeSelf.class'),
      # All these are shaded by the same shading_relocate_package(), which is recursive by default.
      '__shaded_by_pants__/org/pantsbuild/testproject/shadingdep/subpackage/Subpackaged.class',
      '__shaded_by_pants__/org/pantsbuild/testproject/shadingdep/SomeClass.class',
      '__shaded_by_pants__/org/pantsbuild/testproject/shadingdep/Dependency.class',
      # Shaded by a shading_relocate() that completely renames the package and class name.
      'org/pantsbuild/testproject/foo/bar/MyNameIsDifferentNow.class',
    }

    path = os.path.join('dist', 'shading.jar')
    with subsystem_instance(DistributionLocator):
      execute_java = DistributionLocator.cached(minimum_version='1.6').execute_java
      self.assertEquals(0, execute_java(classpath=path,
                                        main='org.pantsbuild.testproject.shading.Main'))
      self.assertEquals(0, execute_java(classpath=path,
                                        main='org.pantsbuild.testproject.foo.bar.MyNameIsDifferentNow'))

    received_classes = set()
    with temporary_dir() as tempdir:
      ZIP.extract(path, tempdir, filter_func=lambda f: f.endswith('.class'))
      for root, dirs, files in os.walk(tempdir):
        for name in files:
          received_classes.add(os.path.relpath(os.path.join(root, name), tempdir))

    self.assertEqual(expected_classes, received_classes)

  def _bundle_and_run(self, bundle_args, classpath):
    self.assert_success(self.run_pants(['clean-all']))
    pants_command = list(bundle_args)
    pants_command.append('testprojects/src/java/org/pantsbuild/testproject/shading:third')
    self.assert_success(self.run_pants(pants_command))

    main_class = 'org.pantsbuild.testproject.shading.Third'
    with subsystem_instance(DistributionLocator):
      executor = SubprocessExecutor(DistributionLocator.cached(minimum_version='1.7'))
      p = executor.spawn(classpath, main_class, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
      out, err = p.communicate()
      self.assertEqual(0, p.returncode, err)
      class_names = json.loads(out.strip())
      self.assertEqual({
        'Gson': 'moc.elgoog.nosg.Gson',
        'Third': 'org.pantsbuild.testproject.shading.Third',
        'Second': 'hello.org.pantsbuild.testproject.shading.Second',
      }, class_names)

  @contextmanager
  def _dist_dir(self):
    with temporary_dir(root_dir=os.path.abspath('.')) as dist_dir:
      yield os.path.relpath(dist_dir)

  def test_no_deployjar_run(self):
    with self._dist_dir() as dist_dir:
      bundle_args = [
        '--pants-distdir={}'.format(dist_dir), 'bundle', '--no-deployjar',
      ]
      classpath=[
        os.path.join(dist_dir, 'third-bundle', 'third.jar'),
        os.path.join(dist_dir, 'third-bundle', 'libs'),
      ]
      self._bundle_and_run(bundle_args, classpath)

  def test_deployjar_run(self):
    with self._dist_dir() as dist_dir:
      bundle_args = [
        '--pants-distdir={}'.format(dist_dir), 'bundle', '--deployjar',
      ]
      classpath=[
        os.path.join(dist_dir, 'third-bundle', 'third.jar'),
      ]
      self._bundle_and_run(bundle_args, classpath)
