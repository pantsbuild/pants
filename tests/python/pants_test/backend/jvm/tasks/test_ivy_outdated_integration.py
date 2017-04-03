# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

from pants.base.build_environment import get_buildroot
from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class IvyOutdatedIntegrationTest(PantsRunIntegrationTest):

  def test_with_no_dependencies(self):
    with temporary_dir(root_dir=get_buildroot()) as tmpdir:
      with open(os.path.join(tmpdir, 'BUILD'), 'w+') as f:
        f.write(dedent("""
        java_library(name='lib')
        """))
      pants_run = self.run_pants(['outdated.ivy', '{}:lib'.format(tmpdir)])
      self.assert_success(pants_run)

      self.assertIn('Dependency updates available:', pants_run.stdout_data)
      self.assertIn('All dependencies are up to date', pants_run.stdout_data)

  def test_with_available_updates(self):
    with temporary_dir(root_dir=get_buildroot()) as tmpdir:
      with open(os.path.join(tmpdir, 'BUILD'), 'w+') as f:
        f.write(dedent("""
        jar_library(name='lib',
          jars=[
            jar(org='commons-io', name='commons-io', rev='2.4',),
            jar(org='org.scala-lang', name='scala-library', rev='2.11.8',)
          ],
        )
        """))
      pants_run = self.run_pants(['outdated.ivy', '{}:lib'.format(tmpdir)])
      self.assert_success(pants_run)

      self.assertNotIn('All dependencies are up to date', pants_run.stdout_data)
      self.assertIn('Dependency updates available:', pants_run.stdout_data)
      self.assertIn('commons-io#commons-io  2.4 -> ', pants_run.stdout_data)
      self.assertIn('org.scala-lang#scala-library  2.11.8 -> ', pants_run.stdout_data)

  def test_with_exclude_coordinates(self):
    with temporary_dir(root_dir=get_buildroot()) as tmpdir:
      with open(os.path.join(tmpdir, 'BUILD'), 'w+') as f:
        f.write(dedent("""
        jar_library(name='lib',
          jars=[
            jar(org='commons-io', name='commons-io', rev='2.4',),
            jar(org='org.scala-lang', name='scala-library', rev='2.11.8',)
          ],
        )
        """))
      pants_run = self.run_pants(['outdated.ivy',
          '--outdated-ivy-exclude-patterns=commons-io:*',
          '{}:{}'.format(tmpdir, 'lib')])
      self.assert_success(pants_run)

      self.assertNotIn('All dependencies are up to date', pants_run.stdout_data)
      self.assertIn('Dependency updates available:', pants_run.stdout_data)
      self.assertNotIn('commons-io#commons-io  2.4 -> ', pants_run.stdout_data)
      self.assertIn('org.scala-lang#scala-library  2.11.8 -> ', pants_run.stdout_data)
