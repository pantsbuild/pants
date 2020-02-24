# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from collections import defaultdict

from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_distribution import PythonDistribution
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.python_tests import PythonTests
from pants.build_graph.files import Files
from pants.build_graph.target import Target
from pants.util.ordered_set import OrderedSet


def is_python_target(tgt: Target) -> bool:
    # We'd like to take all PythonTarget subclasses, but currently PythonThriftLibrary and
    # PythonAntlrLibrary extend PythonTarget, and until we fix that (which we can't do until
    # we remove the old python pipeline entirely) we want to ignore those target types here.
    return isinstance(tgt, (PythonLibrary, PythonTests, PythonBinary))


def has_python_sources(tgt: Target) -> bool:
    return is_python_target(tgt) and tgt.has_sources()


def has_resources(tgt: Target) -> bool:
    return isinstance(tgt, Files) and tgt.has_sources()


def is_local_python_dist(tgt: Target) -> bool:
    return isinstance(tgt, PythonDistribution)


def has_python_requirements(tgt: Target) -> bool:
    return isinstance(tgt, PythonRequirementLibrary)


def always_uses_default_python_platform(tgt: Target) -> bool:
    return isinstance(tgt, PythonTests)


def may_have_explicit_python_platform(tgt: Target) -> bool:
    return isinstance(tgt, PythonBinary)


def targets_by_platform(targets, python_setup):
    targets_requiring_default_platforms = []
    explicit_platform_settings = defaultdict(OrderedSet)
    for target in targets:
        if always_uses_default_python_platform(target):
            targets_requiring_default_platforms.append(target)
        elif may_have_explicit_python_platform(target):
            for platform in target.platforms if target.platforms else python_setup.platforms:
                explicit_platform_settings[platform].add(target)
    # There are currently no tests for this because they're super platform specific and it's hard for
    # us to express that on CI, but https://github.com/pantsbuild/pants/issues/7616 has an excellent
    # repro case for why this is necessary.
    for target in targets_requiring_default_platforms:
        for platform in python_setup.platforms:
            explicit_platform_settings[platform].add(target)
    return dict(explicit_platform_settings)
