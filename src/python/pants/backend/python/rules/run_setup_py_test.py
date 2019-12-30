# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import textwrap
from typing import Iterable, Type

import pytest

from pants.backend.python.python_artifact import PythonArtifact
from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.rules.run_setup_py import (
  AmbiguousOwnerError,
  AncestorInitPyFiles,
  DependencyOwner,
  ExportedTarget,
  ExportedTargetRequirements,
  InvalidEntryPoint,
  NoOwnerError,
  OwnedDependencies,
  OwnedDependency,
  SetupPyChroot,
  SetupPyChrootRequest,
  SetupPySources,
  SetupPySourcesRequest,
  generate_chroot,
  get_ancestor_init_py,
  get_exporting_owner,
  get_owned_dependencies,
  get_requirements,
  get_sources,
)
from pants.build_graph.address import Address
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.fs import Snapshot
from pants.engine.legacy.graph import HydratedTarget, HydratedTargets
from pants.engine.rules import RootRule
from pants.engine.scheduler import ExecutionError
from pants.engine.selectors import Params
from pants.rules.core.strip_source_root import strip_source_root
from pants.source.source_root import SourceRootConfig
from pants.testutil.subsystem.util import init_subsystem
from pants.testutil.test_base import TestBase


class TestSetupPyBase(TestBase):

  @classmethod
  def alias_groups(cls):
    return BuildFileAliases(objects={
      'python_requirement': PythonRequirement,
      'setup_py': PythonArtifact,
    })

  def tgt(self, addr: str) -> HydratedTarget:
    return self.request_single_product(HydratedTarget, Params(Address.parse(addr)))


class TestGetRequirements(TestSetupPyBase):
  @classmethod
  def rules(cls):
    return super().rules() + [
      get_requirements,
      get_owned_dependencies,
      get_exporting_owner,
      RootRule(DependencyOwner),
    ]

  def assert_requirements(self, expected_req_strs, addr):
    reqs = self.request_single_product(
      ExportedTargetRequirements, Params(DependencyOwner(ExportedTarget(self.tgt(addr)))))
    assert sorted(expected_req_strs) == sorted(reqs.requirement_strs)

  def test_get_requirements(self):
    self.create_file('3rdparty/BUILD', textwrap.dedent("""
      python_requirement_library(name='ext1',
        requirements=[python_requirement('ext1==1.22.333')])
      python_requirement_library(name='ext2',
        requirements=[python_requirement('ext2==4.5.6')])
      python_requirement_library(name='ext3',
        requirements=[python_requirement('ext3==0.0.1')])
    """))
    self.create_file('src/python/foo/bar/baz/BUILD',
                     "python_library(dependencies=['3rdparty:ext1'])")
    self.create_file('src/python/foo/bar/qux/BUILD',
                     "python_library(dependencies=['3rdparty:ext2', 'src/python/foo/bar/baz'])")
    self.create_file('src/python/foo/bar/BUILD', textwrap.dedent("""
      python_library(
        dependencies=['src/python/foo/bar/baz', 'src/python/foo/bar/qux'],
        provides=setup_py(name='bar', version='9.8.7')
      )
    """))
    self.create_file('src/python/foo/corge/BUILD', textwrap.dedent("""
      python_library(
        dependencies=['3rdparty:ext3', 'src/python/foo/bar'],
        provides=setup_py(name='corge', version='2.2.2')
      )
    """))

    self.assert_requirements(['ext1==1.22.333', 'ext2==4.5.6'], 'src/python/foo/bar')
    self.assert_requirements(['ext3==0.0.1', 'bar==9.8.7'],
                             'src/python/foo/corge')


class TestGetAncestorInitPy(TestSetupPyBase):
  @classmethod
  def rules(cls):
    return super().rules() + [
      get_ancestor_init_py,
      RootRule(HydratedTargets),
      RootRule(SourceRootConfig),
    ]

  def assert_ancestor_init_py(self, expected_init_pys, addrs):
    ancestor_init_py_files = self.request_single_product(
      AncestorInitPyFiles,
      Params(HydratedTargets([self.tgt(addr) for addr in addrs]),
             SourceRootConfig.global_instance()))
    snapshots = [self.request_single_product(Snapshot, Params(digest))
                 for digest in ancestor_init_py_files.digests]
    init_py_files_found = set([file for snapshot in snapshots for file in snapshot.files])
    # NB: Doesn't include the root __init__.py or the missing src/python/foo/bar/__init__.py.
    assert sorted(expected_init_pys) == sorted(init_py_files_found)

  def test_get_ancestor_init_py(self):
    init_subsystem(SourceRootConfig)
    # NB: src/python/foo/bar/baz/qux/__init__.py is a target's source.
    self.create_file('src/python/foo/bar/baz/qux/BUILD', 'python_library()')
    self.create_file('src/python/foo/bar/baz/qux/qux.py', '')
    self.create_file('src/python/foo/bar/baz/qux/__init__.py', '')
    self.create_file('src/python/foo/bar/baz/__init__.py', '')
    # NB: No src/python/foo/bar/__init__.py.
    # NB: src/python/foo/corge/__init__.py is not any target's source.
    self.create_file('src/python/foo/corge/BUILD', 'python_library(sources=["corge.py"])')
    self.create_file('src/python/foo/corge/corge.py', '')
    self.create_file('src/python/foo/corge/__init__.py', '')
    self.create_file('src/python/foo/__init__.py', '')
    self.create_file('src/python/__init__.py', '')
    self.create_file('src/python/foo/resources/BUILD', 'resources(sources=["style.css"])')
    self.create_file('src/python/foo/resources/style.css', '')
    # NB: A stray __init__.py in a resources-only dir.
    self.create_file('src/python/foo/resources/__init__.py', '')

    # NB: None of these should include the root src/python/__init__.py, the missing
    # src/python/foo/bar/__init__.py, or the stray src/python/foo/resources/__init__.py.
    self.assert_ancestor_init_py(['foo/bar/baz/qux/__init__.py',
                                  'foo/bar/baz/__init__.py',
                                  'foo/__init__.py'],
                                 ['src/python/foo/bar/baz/qux'])
    self.assert_ancestor_init_py([],
                                 ['src/python/foo/resources'])
    self.assert_ancestor_init_py(['foo/corge/__init__.py',
                                  'foo/__init__.py'],
                                 ['src/python/foo/corge', 'src/python/foo/resources'])

    self.assert_ancestor_init_py(['foo/bar/baz/qux/__init__.py',
                                  'foo/bar/baz/__init__.py',
                                  'foo/corge/__init__.py',
                                  'foo/__init__.py'],
                                 ['src/python/foo/bar/baz/qux', 'src/python/foo/corge'])


class TestGetOwnedDependencies(TestSetupPyBase):
  @classmethod
  def rules(cls):
    return super().rules() + [
      get_owned_dependencies,
      get_exporting_owner,
      RootRule(DependencyOwner),
    ]

  def assert_owned(self, owned: Iterable[str], exported: str):
    assert sorted(owned) == sorted(
      od.hydrated_target.address.reference() for od in self.request_single_product(
      OwnedDependencies, Params(DependencyOwner(ExportedTarget(self.tgt(exported))))
    ))

  def test_owned_dependencies(self):
    self.create_file('src/python/foo/bar/baz/BUILD', textwrap.dedent("""
      python_library(name='baz1')
      python_library(name='baz2')
    """))
    self.create_file('src/python/foo/bar/BUILD', textwrap.dedent("""
      python_library(name='bar1',
                     dependencies=['src/python/foo/bar/baz:baz1'],
                     provides=setup_py(name='bar1', version='1.1.1'))
      python_library(name='bar2',
                     dependencies=[':bar-resources', 'src/python/foo/bar/baz:baz2'])
      resources(name='bar-resources')
    """))
    self.create_file('src/python/foo/BUILD', textwrap.dedent("""
      python_library(name='foo',
                     dependencies=['src/python/foo/bar:bar1', 'src/python/foo/bar:bar2'],
                     provides=setup_py(name='foo', version='3.4.5'))
    """))

    self.assert_owned(['src/python/foo/bar:bar1', 'src/python/foo/bar/baz:baz1'],
                      'src/python/foo/bar:bar1')
    self.assert_owned(['src/python/foo', 'src/python/foo/bar:bar2',
                       'src/python/foo/bar:bar-resources', 'src/python/foo/bar/baz:baz2'],
                      'src/python/foo')


class TestGetExportingOwner(TestSetupPyBase):
  @classmethod
  def rules(cls):
    return super().rules() + [
      get_exporting_owner,
      RootRule(OwnedDependency),
    ]

  def assert_is_owner(self, owner: str, owned: str):
    assert (owner ==
            self.request_single_product(
              ExportedTarget,
              Params(OwnedDependency(self.tgt(owned)))).hydrated_target.address.reference())

  def assert_error(self, owned: str, exc_cls: Type[Exception]):
    with pytest.raises(ExecutionError) as excinfo:
      self.request_single_product(ExportedTarget, Params(OwnedDependency(self.tgt(owned))))
    ex = excinfo.value
    assert len(ex.wrapped_exceptions) == 1
    assert type(ex.wrapped_exceptions[0]) == exc_cls

  def assert_no_owner(self, owned: str):
    self.assert_error(owned, NoOwnerError)

  def assert_ambiguous_owner(self, owned: str):
    self.assert_error(owned, AmbiguousOwnerError)

  def test_get_owner_simple(self):
    self.create_file('src/python/foo/bar/baz/BUILD', textwrap.dedent("""
      python_library(name='baz1')
      python_library(name='baz2')
    """))
    self.create_file('src/python/foo/bar/BUILD', textwrap.dedent("""
      python_library(name='bar1',
                     dependencies=['src/python/foo/bar/baz:baz1'],
                     provides=setup_py(name='bar1', version='1.1.1'))
      python_library(name='bar2',
                     dependencies=[':bar-resources', 'src/python/foo/bar/baz:baz2'])
      resources(name='bar-resources')
    """))
    self.create_file('src/python/foo/BUILD', textwrap.dedent("""
      python_library(name='foo1',
                     dependencies=['src/python/foo/bar/baz:baz2'],
                     provides=setup_py(name='foo1', version='0.1.2'))
      python_library(name='foo2')
      python_library(name='foo3',
                     dependencies=['src/python/foo/bar:bar2'],
                     provides=setup_py(name='foo3', version='3.4.5'))
    """))

    self.assert_is_owner('src/python/foo/bar:bar1', 'src/python/foo/bar:bar1')
    self.assert_is_owner('src/python/foo/bar:bar1', 'src/python/foo/bar/baz:baz1')

    self.assert_is_owner('src/python/foo:foo1', 'src/python/foo:foo1')

    self.assert_is_owner('src/python/foo:foo3', 'src/python/foo:foo3')
    self.assert_is_owner('src/python/foo:foo3', 'src/python/foo/bar:bar2')
    self.assert_is_owner('src/python/foo:foo3', 'src/python/foo/bar:bar-resources')

    self.assert_no_owner('src/python/foo:foo2')
    self.assert_ambiguous_owner('src/python/foo/bar/baz:baz2')

  def test_get_owner_siblings(self):
    self.create_file('src/python/siblings/BUILD', textwrap.dedent("""
        python_library(name='sibling1')
        python_library(name='sibling2',
                       dependencies=['src/python/siblings:sibling1'],
                       provides=setup_py(name='siblings', version='2.2.2'))
      """))

    self.assert_is_owner('src/python/siblings:sibling2', 'src/python/siblings:sibling1')
    self.assert_is_owner('src/python/siblings:sibling2', 'src/python/siblings:sibling2')

  def test_get_owner_not_an_ancestor(self):
    self.create_file('src/python/notanancestor/aaa/BUILD', textwrap.dedent("""
        python_library(name='aaa')
      """))
    self.create_file('src/python/notanancestor/bbb/BUILD', textwrap.dedent("""
        python_library(name='bbb',
                       dependencies=['src/python/notanancestor/aaa'],
                       provides=setup_py(name='bbb', version='11.22.33'))
      """))

    self.assert_no_owner('src/python/notanancestor/aaa')
    self.assert_is_owner('src/python/notanancestor/bbb', 'src/python/notanancestor/bbb')

  def test_get_owner_multiple_ancestor_generations(self):
    self.create_file('src/python/aaa/bbb/ccc/BUILD', textwrap.dedent("""
        python_library(name='ccc')
      """))
    self.create_file('src/python/aaa/bbb/BUILD', textwrap.dedent("""
        python_library(name='bbb',
                       dependencies=['src/python/aaa/bbb/ccc'],
                       provides=setup_py(name='bbb', version='1.1.1'))
      """))
    self.create_file('src/python/aaa/BUILD', textwrap.dedent("""
        python_library(name='aaa',
                       dependencies=['src/python/aaa/bbb/ccc'],
                       provides=setup_py(name='aaa', version='2.2.2'))
      """))

    self.assert_is_owner('src/python/aaa/bbb', 'src/python/aaa/bbb/ccc')
    self.assert_is_owner('src/python/aaa/bbb', 'src/python/aaa/bbb')
    self.assert_is_owner('src/python/aaa', 'src/python/aaa')
