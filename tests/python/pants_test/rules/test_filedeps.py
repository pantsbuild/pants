# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from future.utils import text_type
from mock import Mock
from pex.orderedset import OrderedSet

from pants.build_graph.address import Address, BuildFileAddress
from pants.engine.addressable import BuildFileAddresses
from pants.engine.fs import PathGlobsAndRoot, PathGlobs
from pants.engine.legacy.graph import HydratedTarget, TransitiveHydratedTargets
from pants.engine.legacy.structs import TargetAdaptor
from pants.rules.core.filedeps import file_deps
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_file_dump
from pants.util.meta import AbstractClass
from pants.util.objects import datatype
from pants_test.engine.scheduler_test_base import SchedulerTestBase
from pants_test.engine.util import MockConsole, run_rule
from pants_test.test_base import TestBase


class FileDepsTest(TestBase, SchedulerTestBase, AbstractClass):

  def filedeps_rule_test(self, target_addresses, transitive_targets, expected_console_output):
    console = MockConsole()

    run_rule(file_deps, console, transitive_targets)

    self.assertEquals(console.stdout.getvalue(), expected_console_output)

  def make_build_target_address(self, spec):
    address = Address.parse(spec)
    
    return BuildFileAddress(
      build_file=None,
      target_name=address.target_name,
      rel_path='{}/BUILD'.format(address.spec_path),
    )

  def make_build_target_address_with_ext(self, spec):
    address = Address.parse(spec)

    return BuildFileAddress(
      build_file=None,
      target_name=address.target_name,
      rel_path='{}/BUILD.ext'.format(address.spec_path),
    )

  def make_snapshot(self, files):
    with temporary_dir() as temp_dir:
      for file_name, content in files.items():
        safe_file_dump(os.path.join(temp_dir, file_name), content)
      return self.scheduler.capture_snapshots((
        PathGlobsAndRoot(PathGlobs(('**',)), text_type(temp_dir)),
      ))[0]
    
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
      [],
      transitive_targets,
      ""
    )

  def test_output_one_target_no_source(self):
    target_address = self.make_build_target_address("some/target")
    hydrated_target = self.mock_hydrated_target(target_address, {}, ())
    
    transitive_targets = TransitiveHydratedTargets(
      (hydrated_target,),
      {hydrated_target}
    )
    
    self.filedeps_rule_test(
      [target_address],
      transitive_targets,
      "some/target/BUILD\n"
    )

  def test_output_one_target_one_source(self):
    target_address = self.make_build_target_address("some/target")
    hydrated_target = self.mock_hydrated_target(target_address, {"some/file.py": "", }, ())
    
    transitive_targets = TransitiveHydratedTargets(
      (hydrated_target,),
      {hydrated_target}
    )
    
    self.filedeps_rule_test(
      [target_address],
      transitive_targets,
      '''some/target/BUILD
some/file.py
''')

  def test_output_one_target_no_source_one_dep(self):
    dep_address = self.make_build_target_address("other/target")
    dep_target = self.mock_hydrated_target(dep_address, {"other/file.py": "", }, ())
    
    target_address = self.make_build_target_address("some/target")   
    hydrated_target = self.mock_hydrated_target(target_address, {}, (dep_target,))
    
    transitive_targets = TransitiveHydratedTargets(
      (hydrated_target,), 
      OrderedSet([hydrated_target, dep_target])
    )
    
    self.filedeps_rule_test(
      [target_address],
      transitive_targets,
      '''some/target/BUILD
other/target/BUILD
other/file.py
''')

  def test_output_one_target_one_source_with_dep(self):
    dep_address = self.make_build_target_address("other/target")
    dep_target = self.mock_hydrated_target(dep_address, {"other/file.py": "", }, ())
    
    target_address = self.make_build_target_address("some/target")
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
      [target_address],
      transitive_targets,
      '''some/target/BUILD
some/file.py
other/target/BUILD
other/file.py
''')

  def test_output_multiple_targets_one_source(self):
    target_address1 = self.make_build_target_address("some/target")
    hydrated_target1 = self.mock_hydrated_target(target_address1, {"some/file.py": "", }, ())
    
    target_address2 = self.make_build_target_address("other/target")
    hydrated_target2 = self.mock_hydrated_target(target_address2, {"other/file.py": "", }, ())
     
    transitive_targets = TransitiveHydratedTargets(
      (hydrated_target1, hydrated_target2), 
      OrderedSet([hydrated_target1, hydrated_target2])
    )
    
    self.filedeps_rule_test(
      [target_address1, target_address2],
      transitive_targets,
      '''some/target/BUILD
some/file.py
other/target/BUILD
other/file.py
''')

  def test_outputs_multiple_targets_one_source_with_dep(self):
    #   target1    target2
    #   /
    #  dep
    dep_address1 = self.make_build_target_address("dep1/target")
    dep_target1 = self.mock_hydrated_target(dep_address1, {"dep1/file.py": "", }, ())
    
    target_address1 = self.make_build_target_address("some/target")
    hydrated_target1 = self.mock_hydrated_target(
      target_address1,
      {"some/file.py": "", },
      (dep_target1,)
    )

    dep_address2 = self.make_build_target_address("dep2/target")
    dep_target2 = self.mock_hydrated_target(dep_address2, {"dep2/file.py": "", }, ())

    target_address2 = self.make_build_target_address("other/target")
    hydrated_target2 = self.mock_hydrated_target(
      target_address2,
      {"other/file.py": "", },
      (dep_target2,))
 
    transitive_targets = TransitiveHydratedTargets(
      (hydrated_target1, hydrated_target2), 
      OrderedSet([hydrated_target1, hydrated_target2, dep_target1, dep_target2])
    )
    
    self.filedeps_rule_test(
      [target_address1, target_address2],
      transitive_targets,
      '''some/target/BUILD
some/file.py
other/target/BUILD
other/file.py
dep1/target/BUILD
dep1/file.py
dep2/target/BUILD
dep2/file.py
''')

  def test_output_multiple_targets_one_source_overlapping(self):
    dep_address = self.make_build_target_address("dep/target")
    dep_target = self.mock_hydrated_target(dep_address, {"dep/file.py": "", }, ())
  
    target_address1 = self.make_build_target_address("some/target")
    hydrated_target1 = self.mock_hydrated_target(
      target_address1,
      {"some/file.py": "", },
      (dep_target,)
    )
    
    target_address2 = self.make_build_target_address("some/target")
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
      [target_address1, target_address2],
      transitive_targets,
      '''some/target/BUILD
some/file.py
dep/target/BUILD
dep/file.py
''')

  def test_output_one_target_multiple_source(self):
    target_address = self.make_build_target_address("some/target")
    hydrated_target = self.mock_hydrated_target(
      target_address,
      {
        "some/file1.py": "",
        "some/file2.py": "",
      }, ())

    transitive_targets = TransitiveHydratedTargets((hydrated_target,), {hydrated_target})

    self.filedeps_rule_test(
      [target_address],
      transitive_targets,
      '''some/target/BUILD
some/file1.py
some/file2.py
''')

  def test_output_one_target_build_with_ext_no_source(self):
    target_address = self.make_build_target_address_with_ext("some/target")
    hydrated_target = self.mock_hydrated_target(target_address, {}, ())

    transitive_targets = TransitiveHydratedTargets((hydrated_target,), {hydrated_target})

    self.filedeps_rule_test(
      [target_address],
      transitive_targets,
      'some/target/BUILD.ext\n')
