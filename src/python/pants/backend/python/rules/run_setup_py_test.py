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
