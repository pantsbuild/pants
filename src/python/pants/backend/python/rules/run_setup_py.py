# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
from dataclasses import dataclass
from typing import List, Set, Tuple

from pants.backend.python.rules.pex import (
  CreatePex,
  Pex,
  PexInterpreterConstraints,
  PexRequirements,
)
from pants.backend.python.rules.setup_py_util import (
  PackageDatum,
  distutils_repr,
  find_packages,
  source_root_or_raise,
)
from pants.backend.python.rules.setuptools import Setuptools
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.base.specs import AscendantAddresses, Specs
from pants.build_graph.address import Address
from pants.engine.addressable import BuildFileAddresses
from pants.engine.console import Console
from pants.engine.fs import (
  Digest,
  DirectoriesToMerge,
  DirectoryToMaterialize,
  DirectoryWithPrefixToAdd,
  DirectoryWithPrefixToStrip,
  FileContent,
  InputFilesContent,
  PathGlobs,
  Snapshot,
  Workspace,
)
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.isolated_process import ExecuteProcessRequest, ExecuteProcessResult
from pants.engine.legacy.graph import HydratedTarget, HydratedTargets, TransitiveHydratedTargets
from pants.engine.legacy.structs import PythonBinaryAdaptor, PythonTargetAdaptor, ResourcesAdaptor
from pants.engine.objects import Collection
from pants.engine.rules import console_rule, optionable_rule, rule
from pants.engine.selectors import Get, MultiGet
from pants.rules.core.distdir import DistDir
from pants.rules.core.strip_source_root import SourceRootStrippedSources
from pants.source.source_root import SourceRootConfig

