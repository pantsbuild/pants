# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import unittest
from textwrap import dedent

from mock import Mock
from pex.orderedset import OrderedSet

from pants.build_graph.address import Address, BuildFileAddress
from pants.engine.legacy.graph import HydratedTarget, TransitiveHydratedTargets
from pants.rules.core.filedeps import file_deps
from pants_test.engine.util import MockConsole, run_rule
from pants_test.test_base import TestBase


@unittest.skip(reason='Bitrot discovered during #6880: should be ported to ConsoleRuleTestBase.')
class FileDepsTest(TestBase):

  def filedeps_rule_test(self, transitive_targets, expected_console_output):
    console = MockConsole()

    run_rule(file_deps, console, transitive_targets)

    self.assertEquals(console.stdout.getvalue(), expected_console_output)
  
  @staticmethod
  def make_build_target_address(spec, ext=""):
    address = Address.parse(spec)
    return BuildFileAddress(
      target_name=address.target_name,
      rel_path='{}/BUILD{}'.format(address.spec_path, ext),
    )
    
  def mock_target_adaptor(self, source_files_in_dict):
    adaptor = Mock()
    adaptor.sources = Mock()
    adaptor.sources.snapshot = self.make_snapshot(source_files_in_dict)
    return adaptor

  def mock_hydrated_target(self, target_address, source_files_in_dict, dependencies):
    adaptor = self.mock_target_adaptor(source_files_in_dict)
    return HydratedTarget(target_address, adaptor, tuple(d.address for d in dependencies))

  def test_output_no_target(self):
    transitive_targets = TransitiveHydratedTargets((), set())
    
    self.filedeps_rule_test(
      transitive_targets,
      ""
    )

  def test_output_one_target_no_source(self):
    target_address = FileDepsTest.make_build_target_address("some/target")
    hydrated_target = self.mock_hydrated_target(target_address, {}, ())
    
    transitive_targets = TransitiveHydratedTargets(
      (hydrated_target,),
      {hydrated_target}
    )
    
    self.filedeps_rule_test(
      transitive_targets,
      "some/target/BUILD\n"
    )

  def test_output_one_target_one_source(self):
    target_address = FileDepsTest.make_build_target_address("some/target")
    hydrated_target = self.mock_hydrated_target(target_address, {"some/file.py": "", }, ())
    
    transitive_targets = TransitiveHydratedTargets(
      (hydrated_target,),
      {hydrated_target}
    )
    
    self.filedeps_rule_test(
      transitive_targets,
      dedent(
        '''\
        some/target/BUILD
        some/file.py
        ''')
    )

  def test_output_one_target_no_source_one_dep(self):
    dep_address = FileDepsTest.make_build_target_address("dep/target")
    dep_target = self.mock_hydrated_target(dep_address, {"dep/file.py": "", }, ())
    
    target_address = FileDepsTest.make_build_target_address("some/target")
    hydrated_target = self.mock_hydrated_target(target_address, {}, (dep_target,))
    
    transitive_targets = TransitiveHydratedTargets(
      (hydrated_target,), 
      OrderedSet([hydrated_target, dep_target])
    )
    
    self.filedeps_rule_test(
      transitive_targets,
      dedent(
        '''\
        some/target/BUILD
        dep/target/BUILD
        dep/file.py
        ''')
    )

  def test_output_one_target_one_source_with_dep(self):
    dep_address = FileDepsTest.make_build_target_address("dep/target")
    dep_target = self.mock_hydrated_target(dep_address, {"dep/file.py": "", }, ())
    
    target_address = FileDepsTest.make_build_target_address("some/target")
    hydrated_target = self.mock_hydrated_target(
      target_address, 
      {"some/file.py": "", },
      (dep_target,)
    )
    
    transitive_targets = TransitiveHydratedTargets(
      (hydrated_target,),
      OrderedSet([hydrated_target, dep_target])
    )
    
    self.filedeps_rule_test(
      transitive_targets,
      dedent(
        '''\
        some/target/BUILD
        some/file.py
        dep/target/BUILD
        dep/file.py
        ''')
    )

  def test_output_multiple_targets_one_source(self):
    target_address1 = FileDepsTest.make_build_target_address("some/target")
    hydrated_target1 = self.mock_hydrated_target(target_address1, {"some/file.py": "", }, ())
    
    target_address2 = FileDepsTest.make_build_target_address("other/target")
    hydrated_target2 = self.mock_hydrated_target(target_address2, {"other/file.py": "", }, ())
     
    transitive_targets = TransitiveHydratedTargets(
      (hydrated_target1, hydrated_target2), 
      OrderedSet([hydrated_target1, hydrated_target2])
    )
    
    self.filedeps_rule_test(
      transitive_targets,
      dedent(
        '''\
        some/target/BUILD
        some/file.py
        other/target/BUILD
        other/file.py
        ''')
    )

  def test_outputs_multiple_targets_one_source_with_dep(self):
    #   target1                 target2
    #  source="some/file.py"  source="other/file.py"
    #   /                       /
    #  dep1                   dep2
    dep_address1 = FileDepsTest.make_build_target_address("dep1/target")
    dep_target1 = self.mock_hydrated_target(dep_address1, {"dep1/file.py": "", }, ())
    
    target_address1 = FileDepsTest.make_build_target_address("some/target")
    hydrated_target1 = self.mock_hydrated_target(
      target_address1,
      {"some/file.py": "", },
      (dep_target1,)
    )

    dep_address2 = FileDepsTest.make_build_target_address("dep2/target")
    dep_target2 = self.mock_hydrated_target(dep_address2, {"dep2/file.py": "", }, ())

    target_address2 = FileDepsTest.make_build_target_address("other/target")
    hydrated_target2 = self.mock_hydrated_target(
      target_address2,
      {"other/file.py": "", },
      (dep_target2,))
 
    transitive_targets = TransitiveHydratedTargets(
      (hydrated_target1, hydrated_target2), 
      OrderedSet([hydrated_target1, hydrated_target2, dep_target1, dep_target2])
    )
    
    self.filedeps_rule_test(
      transitive_targets,
      dedent(
        '''\
        some/target/BUILD
        some/file.py
        other/target/BUILD
        other/file.py
        dep1/target/BUILD
        dep1/file.py
        dep2/target/BUILD
        dep2/file.py
        ''')
    )

  def test_output_multiple_targets_one_source_overlapping(self):
    #   target1                target2
    #  source="some/file.py"  source="some/file.py"
    #   /                      /
    #  dep                   dep
    dep_address = FileDepsTest.make_build_target_address("dep/target")
    dep_target = self.mock_hydrated_target(dep_address, {"dep/file.py": "", }, ())
  
    target_address1 = FileDepsTest.make_build_target_address("some/target")
    hydrated_target1 = self.mock_hydrated_target(
      target_address1,
      {"some/file.py": "", },
      (dep_target,)
    )
    
    target_address2 = FileDepsTest.make_build_target_address("some/target")
    hydrated_target2 = self.mock_hydrated_target(
      target_address2,
      {"some/file.py": "", },
      (dep_target,)
    )
    
    transitive_targets = TransitiveHydratedTargets(
      (hydrated_target1, hydrated_target2),
      OrderedSet([hydrated_target1, hydrated_target2, dep_target])
    )

    self.filedeps_rule_test(
      transitive_targets,
      dedent(
        '''\
        some/target/BUILD
        some/file.py
        dep/target/BUILD
        dep/file.py
        ''')
    )

  def test_output_one_target_multiple_source(self):
    target_address = FileDepsTest.make_build_target_address("some/target")
    hydrated_target = self.mock_hydrated_target(
      target_address,
      {
        "some/file1.py": "",
        "some/file2.py": "",
      }, ())

    transitive_targets = TransitiveHydratedTargets((hydrated_target,), {hydrated_target})

    self.filedeps_rule_test(
      transitive_targets,
      dedent(
        '''\
        some/target/BUILD
        some/file1.py
        some/file2.py
        ''')
    )

  def test_output_one_target_build_with_ext_no_source(self):
    target_address = FileDepsTest.make_build_target_address("some/target", ".ext")
    hydrated_target = self.mock_hydrated_target(target_address, {}, ())

    transitive_targets = TransitiveHydratedTargets((hydrated_target,), {hydrated_target})

    self.filedeps_rule_test(
      transitive_targets,
      'some/target/BUILD.ext\n')
