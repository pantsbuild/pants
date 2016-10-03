# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os
from textwrap import dedent

from pants.base.build_environment import get_buildroot
from pants.fs.archive import ZIP
from pants.java.distribution.distribution import DistributionLocator
from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.subsystem.subsystem_util import init_subsystem


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
    init_subsystem(DistributionLocator)
    execute_java = DistributionLocator.cached(minimum_version='1.6').execute_java
    self.assertEquals(0, execute_java(classpath=[path],
                                      main='org.pantsbuild.testproject.shading.Main'))
    self.assertEquals(0, execute_java(classpath=[path],
                                      main='org.pantsbuild.testproject.foo.bar.MyNameIsDifferentNow'))

    received_classes = set()
    with temporary_dir() as tempdir:
      ZIP.extract(path, tempdir, filter_func=lambda f: f.endswith('.class'))
      for root, dirs, files in os.walk(tempdir):
        for name in files:
          received_classes.add(os.path.relpath(os.path.join(root, name), tempdir))

    self.assertEqual(expected_classes, received_classes)

  def test_no_deployjar_run(self):
    """Shading continues to work with --no-deployjar.

    All jars including the main jar as well as libraries will run through shader.
    """
    self.assertEquals({
          'Gson': 'moc.elgoog.nosg.Gson',
          'Third': 'org.pantsbuild.testproject.shading.Third',
          'Second': 'hello.org.pantsbuild.testproject.shading.Second',
      },
      json.loads(self.bundle_and_run(
        'testprojects/src/java/org/pantsbuild/testproject/shading:third',
        'testprojects.src.java.org.pantsbuild.testproject.shading.third',
        bundle_jar_name='third',
        bundle_options=['--no-deployjar'],
        # The shaded jars are no longer symlinks to .pants.d, they are actual files.
        library_jars_are_symlinks=False,
        expected_bundle_content=[
          'libs/3rdparty.gson-0.jar',
          'libs/testprojects.src.java.org.pantsbuild.testproject.shading.third_lib-0.jar',
          'third.jar']).strip()))

  def test_deployjar_run(self):
    self.assertEquals({
          'Gson': 'moc.elgoog.nosg.Gson',
          'Third': 'org.pantsbuild.testproject.shading.Third',
          'Second': 'hello.org.pantsbuild.testproject.shading.Second',
      },
      json.loads(self.bundle_and_run(
        'testprojects/src/java/org/pantsbuild/testproject/shading:third',
        'testprojects.src.java.org.pantsbuild.testproject.shading.third',
        bundle_jar_name='third',
        bundle_options=['--deployjar'],
        expected_bundle_content=[
          'third.jar']).strip()))

  def test_shading_does_not_influence_permissions(self):
    with temporary_dir(root_dir=get_buildroot()) as tmpdir:
      tmp_name = os.path.basename(tmpdir)
      with open(os.path.join(tmpdir, 'Foo.java'), 'w+') as f:
        f.write('public class Foo {}\n')
      with open(os.path.join(tmpdir, 'BUILD.lib'), 'w+') as f:
        f.write(dedent("""
          java_library(name='lib',
            sources=['Foo.java'],
          )
        """))
      with open(os.path.join(tmpdir, 'BUILD'), 'w+') as f:
        f.write(dedent("""
          jvm_binary(name='{name}',
            basename='{name}',
            dependencies=[
              ':lib',
            ],
          )
        """).format(name=tmp_name))

      jar_path = os.path.join('dist', '{}.jar'.format(tmp_name))

      # Build a binary with no shading, and record the permissions.
      self.run_pants(['clean-all'])
      self.assert_success(self.run_pants(['binary', tmpdir]))
      permissions = os.stat(jar_path).st_mode

      with open(os.path.join(tmpdir, 'BUILD'), 'w') as f:
        f.write(dedent("""
          jvm_binary(name='{name}',
            basename='{name}',
            dependencies=[
              ':lib',
            ],
            shading_rules=[
              shading_relocate_package('org.foo.bar'),
            ],
          )
        """).format(name=tmp_name))

      # Build the binary again with shading; permissions shouldn't be different.
      self.run_pants(['clean-all'])
      os.remove(jar_path)
      self.assert_success(self.run_pants(['binary', tmpdir]))
      self.assertEquals(permissions, os.stat(jar_path).st_mode)
