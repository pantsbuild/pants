# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import os.path
import pkgutil
import subprocess
from dataclasses import dataclass
from textwrap import dedent

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.goals import package_dists, package_pex_binary
from pants.backend.python.goals.package_pex_binary import (
    PexBinaryFieldSet,
    PexFromTargetsRequestForBuiltPackage,
)
from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.providers.python_build_standalone import rules as pbs
from pants.backend.python.target_types import (
    PexBinary,
    PexLayout,
    PythonDistribution,
    PythonRequirementTarget,
    PythonSourcesGeneratorTarget,
)
from pants.backend.python.util_rules import pex_from_targets
from pants.build_graph.address import Address
from pants.core.goals.package import BuiltPackage
from pants.core.target_types import (
    FilesGeneratorTarget,
    FileTarget,
    RelocatedFiles,
    ResourcesGeneratorTarget,
)
from pants.core.target_types import rules as core_target_types_rules
from pants.testutil.python_interpreter_selection import skip_unless_python38_present
from pants.testutil.python_rule_runner import PythonRuleRunner
from pants.testutil.rule_runner import QueryRule
from pants.testutil.skip_utils import skip_if_linux_arm64

from pants.backend.python.target_types import (
    PexArgsField,
    PexBinaryDefaults,
    PexCheckField,
    PexCompletePlatformsField,
    PexEmitWarningsField,
    PexEntryPointField,
    PexEnvField,
    PexExecutableField,
    PexExecutionMode,
    PexExecutionModeField,
    PexExtraBuildArgsField,
    PexIgnoreErrorsField,
    PexIncludeRequirementsField,
    PexIncludeSourcesField,
    PexIncludeToolsField,
    PexInheritPathField,
    PexLayout,
    PexLayoutField,
    PexScieField,
    PexScriptField,
    PexShBootField,
    PexShebangField,
    PexStripEnvField,
    PexVenvHermeticScripts,
    PexVenvSitePackagesCopies,
    ResolvePexEntryPointRequest,
)
from pants.backend.python.target_types import (
    PexSciePlatformField    ,
    PexScieHashAlgField,
    PexArgsField,
    PexBinaryDefaults,
    PexCheckField,
    PexCompletePlatformsField,
    PexEmitWarningsField,
    PexEntryPointField,
    PexEnvField,
    PexExecutableField,
    PexExecutionMode,
    PexExecutionModeField,
    PexExtraBuildArgsField,
    PexIgnoreErrorsField,
    PexIncludeRequirementsField,
    PexIncludeSourcesField,
    PexIncludeToolsField,
    PexInheritPathField,
    PexLayout,
    PexLayoutField,
    PexScieField,
    PexScieNameStyleField,
    PexScriptField,
    PexShBootField,
    PexShebangField,
    PexStripEnvField,
    PexVenvHermeticScripts,
    PexVenvSitePackagesCopies,
    ResolvePexEntryPointRequest,
)

from pants.backend.python.target_types import (
    PexSciePlatformField    ,
    PexScieHashAlgField,
    ScieNameStyle,
    PexArgsField,
    PexBinaryDefaults,
    PexCheckField,
    PexCompletePlatformsField,
    PexEmitWarningsField,
    PexEntryPointField,
    PexEnvField,
    PexExecutableField,
    PexExecutionMode,
    PexExecutionModeField,
    PexExtraBuildArgsField,
    PexIgnoreErrorsField,
    PexIncludeRequirementsField,
    PexIncludeSourcesField,
    PexIncludeToolsField,
    PexInheritPathField,
    PexLayout,
    PexLayoutField,
    PexScieField,
    PexScieNameStyleField,
    PexScriptField,
    PexShBootField,
    PexShebangField,
    PexStripEnvField,
    PexVenvHermeticScripts,
    PexVenvSitePackagesCopies,
    ResolvePexEntryPointRequest,
)
from collections.abc import Iterable, Iterator, Mapping, Sequence

from pants.backend.python.goals.package_pex_binary import _scie_output_filenames, _scie_output_directories

def test_files_default():
    example = 'helloworld/example_pex'
    assert (example,) == _scie_output_filenames(example,
                                                PexScieNameStyleField.default,
                                                PexSciePlatformField.default,
                                                PexScieHashAlgField.default)

def test_files_default_with_hash():
    example = 'helloworld/example_pex'
    assert (example,example + '.md5') == _scie_output_filenames(example,
                                                PexScieNameStyleField.default,
                                                PexSciePlatformField.default,
                                                'md5')
    
def test_files_parent_dir():
    example = 'helloworld/example_pex'
    assert None == _scie_output_filenames(example,
                                                ScieNameStyle.PLATFORM_PARENT_DIR,
                                                ['linux-aarch64','linux-armv7l','linux-powerpc64'],
                                                'sha256')

def    test_files_platform_suffix():

    assert ('foo/bar-linux-aarch64', 'foo/bar-linux-x86_64') == _scie_output_filenames('foo/bar',
                                                                                       ScieNameStyle.PLATFORM_FILE_SUFFIX,
                                                                                       ['linux-aarch64','linux-x86_64'],
                                                                                       PexScieHashAlgField.default
                                                )

def    test_files_platform_suffix_hash():
    assert ('foo/bar-linux-aarch64','foo/bar-linux-aarch64.sha256', 'foo/bar-linux-x86_64', 'foo/bar-linux-x86_64.sha256') == _scie_output_filenames('foo/bar',
                                                ScieNameStyle.PLATFORM_FILE_SUFFIX,
                                                                                                                                                     ['linux-aarch64','linux-x86_64'],
                                                'sha256')
    

def test_dirs_default():
    example = 'helloworld/example_pex'
    assert None == _scie_output_directories(example,
                                          PexScieNameStyleField.default,
                                          PexSciePlatformField.default)

def test_dirs_platform_no_change():
    example = 'helloworld/example_pex'
    assert None == _scie_output_directories(example,
                                          PexScieNameStyleField.default,
                                          ['linux-aarch64','linux-x86_64'])

def test_dirs_platform_parent_dir():
    example = 'helloworld/example_pex'
    assert ('helloworld/linux-aarch64','helloworld/linux-x86_64') == _scie_output_directories(example,
                                          ScieNameStyle.PLATFORM_PARENT_DIR,
                                          ['linux-aarch64','linux-x86_64'])
    
