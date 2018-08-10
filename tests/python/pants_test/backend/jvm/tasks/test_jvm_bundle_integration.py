# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class BundleIntegrationTest(PantsRunIntegrationTest):

  def test_bundle_of_nonascii_classes(self):
    """JVM classes can have non-ASCII names. Make sure we don't assume ASCII."""

    stdout = self.bundle_and_run(
      'testprojects/src/java/org/pantsbuild/testproject/unicode/main',
      'testprojects.src.java.org.pantsbuild.testproject.unicode.main.main',
      bundle_jar_name='unicode-testproject')
    self.assertIn("Have a nice day one!", stdout)
    self.assertIn("shapeless success", stdout)

  def test_bundle_colliding_resources(self):
    """Tests that the proper resource is bundled with each of these bundled targets when
    each project has a different resource with the same path.
    """
    for name in ['a', 'b', 'c']:
      target = ('testprojects/maven_layout/resource_collision/example_{name}/'
                'src/main/java/org/pantsbuild/duplicateres/example{name}/'
                .format(name=name))
      bundle_name = 'example{name}'.format(name=name)
      stdout = self.bundle_and_run(target, bundle_name, bundle_jar_name=bundle_name, bundle_options=[
          '--bundle-jvm-use-basename-prefix',
        ])
      self.assertEqual(stdout, 'Hello world!: resource from example {name}\n'.format(name=name))
