# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os
import xml.etree.ElementTree as ET
from collections import namedtuple
from textwrap import dedent

from twitter.common.collections import OrderedSet

from pants.backend.jvm.ivy_utils import (FrozenResolution, IvyFetchStep, IvyInfo, IvyModule,
                                         IvyModuleRef, IvyResolveMappingError, IvyResolveResult,
                                         IvyResolveStep, IvyUtils)
from pants.backend.jvm.register import build_file_aliases as register_jvm
from pants.backend.jvm.resolution_utils import ResolutionUtils
from pants.backend.jvm.subsystems.jar_dependency_management import JarDependencyManagement
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.base.build_environment import get_buildroot
from pants.build_graph.register import build_file_aliases as register_core
from pants.ivy.ivy_subsystem import IvySubsystem
from pants.java.jar.exclude import Exclude
from pants.java.jar.jar_dependency import JarDependency
from pants.java.jar.jar_dependency_utils import M2Coordinate
from pants.util.contextutil import temporary_dir, temporary_file, temporary_file_path
from pants_test.base_test import BaseTest
from pants_test.subsystem.subsystem_util import init_subsystem


class ResolutionUtilsTest(BaseTest):
  # TODO is necessary?
  @property
  def alias_groups(self):
    return register_core().merge(register_jvm())


  # copied from IvyUtils
  def setUp(self):
    super(ResolutionUtilsTest, self).setUp()

    self.add_to_build_file('src/java/targets',
        dedent("""
            jar_library(
              name='a',
              jars=[
                jar('org1', 'name1', 'rev1'),
                jar('org2', 'name2', 'rev2', force=True),
              ],
            )
        """))

    self.b_org = 'com.example'
    self.b_name = 'b'
    self.add_to_build_file('src/java/targets',
        dedent("""
            java_library(
              name='b',
              dependencies=[':a'],
              provides=artifact('{org}', '{name}', repo=repository()),
              sources=['z.java'],
            )
        """.format(org=self.b_org, name=self.b_name)))

    self.add_to_build_file('3rdparty',
        dedent("""
            jar_library(
              name='example-morx',
              jars = [
                jar(org='commons-lang', name='commons-lang', rev='2.5', classifier='morx'),
              ]
            )
            jar_library(
              name='example-fleem',
              jars = [
                jar(org='commons-lang', name='commons-lang', rev='2.5', classifier='fleem'),
              ]
            )
        """))

    self.add_to_build_file('src/java/targets',
        dedent("""
            java_library(
              name='c',
              dependencies=[
                '3rdparty:example-morx',
                '3rdparty:example-fleem',
              ],
              sources=['w.java'],
            )
        """.format(org=self.b_org, name=self.b_name)))

    self.add_to_build_file('src/java/targets',
        dedent("""
            java_library(
              name='e',
              dependencies=[
                '3rdparty:example-morx',
                '3rdparty:example-fleem',
              ],
              excludes=[exclude(org='commons-lang', name='commons-lang')],
              sources=['w.java'],
            )
        """.format(org=self.b_org, name=self.b_name)))

    self.a = self.target('src/java/targets:a')
    self.b = self.target('src/java/targets:b')
    self.c = self.target('src/java/targets:c')
    self.e = self.target('src/java/targets:e')

  def test_exclude_exported(self):
    jars, excludes = ResolutionUtils.calculate_classpath([self.b])
    for jar in jars:
      self.assertEqual(jar.excludes, (Exclude(self.b_org, self.b_name),))
    self.assertEqual(excludes, set())

  def test_excludes_are_generated(self):
    _, excludes = ResolutionUtils.calculate_classpath([self.e])
    self.assertSetEqual(excludes, {Exclude(org='commons-lang', name='commons-lang')})

  def test_classifiers(self):
    jars, _ = ResolutionUtils.calculate_classpath([self.c])

    jars.sort(key=lambda jar: jar.classifier)

    self.assertEquals(['fleem', 'morx'], [jar.classifier for jar in jars])

  def test_resolve_conflict_missing_versions(self):
    v1 = JarDependency('org.example', 'foo', None, force=False)
    v2 = JarDependency('org.example', 'foo', '2', force=False)
    self.assertIs(v2, ResolutionUtils._resolve_conflict(v1, v2))
    self.assertIs(v2, ResolutionUtils._resolve_conflict(v2, v1))

  def test_resove_conflict_no_conflicts(self):
    v1 = JarDependency('org.example', 'foo', '1', force=False)
    v1_force = JarDependency('org.example', 'foo', '1', force=True)
    v2 = JarDependency('org.example', 'foo', '2', force=False)

    # If neither version is forced, use the latest version.
    self.assertIs(v2, ResolutionUtils._resolve_conflict(v1, v2))
    self.assertIs(v2, ResolutionUtils._resolve_conflict(v2, v1))

    # If an earlier version is forced, use the forced version.
    self.assertIs(v1_force, ResolutionUtils._resolve_conflict(v1_force, v2))
    self.assertIs(v1_force, ResolutionUtils._resolve_conflict(v2, v1_force))

    # If the same version is forced, use the forced version.
    self.assertIs(v1_force, ResolutionUtils._resolve_conflict(v1, v1_force))
    self.assertIs(v1_force, ResolutionUtils._resolve_conflict(v1_force, v1))

    # If the same force is in play in multiple locations, allow it.
    self.assertIs(v1_force, ResolutionUtils._resolve_conflict(v1_force, v1_force))

  def test_resolve_conflict_conflict(self):
    v1_force = JarDependency('org.example', 'foo', '1', force=True)
    v2_force = JarDependency('org.example', 'foo', '2', force=True)

    with self.assertRaises(ResolutionUtils.JvmResolveConflictingDepsError):
      ResolutionUtils._resolve_conflict(v1_force, v2_force)

    with self.assertRaises(ResolutionUtils.JvmResolveConflictingDepsError):
      ResolutionUtils._resolve_conflict(v2_force, v1_force)
