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
