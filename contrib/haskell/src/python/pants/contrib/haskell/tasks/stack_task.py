# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess
from abc import abstractmethod

from pants.backend.core.tasks.task import Task
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.util.dirutil import safe_mkdir

from pants.contrib.haskell.targets.cabal import Cabal
from pants.contrib.haskell.targets.hackage import Hackage
from pants.contrib.haskell.targets.haskell_package import HaskellPackage


class StackTask(Task):
  """Abstract class that all other `stack` tasks inherit from"""

  @property
  def cache_target_dirs(self):
    return True

  @staticmethod
  def is_hackage(target):
    return isinstance(target, Hackage)

  @staticmethod
  def is_cabal(target):
    return isinstance(target, Cabal)

  @staticmethod
  def is_haskell_package(target):
    return isinstance(target, HaskellPackage)

  @staticmethod
  def make_stack_yaml(target):
    """
    Build a `stack.yaml` file from a root target's dependency graph:

    * Every `stackage` target is currently ignored since they are already covered
      by the `resolver` field
    * Every `hackage` target translates to an `extra-deps` entry
    * Every `cabal` target translates to a `package` entry
    """
    for dependency in filter(StackTask.is_haskell_package, target.closure()):
      if target.resolver != dependency.resolver:
        raise TaskError('''
Every package in a Haskell build graph must use the same resolver.

Root target : {root}
  - Resolver: {root_resolver}
Dependency  : {dep}
  - Resolver: {dep_resolver}
'''.strip().format(root=target.address.spec,
                   root_resolver=target.resolver,
                   dep=dependency.address.spec,
                   dep_resolver=dependency.resolver))

    packages = [target] + target.dependencies

    hackage_packages = filter(StackTask.is_hackage, packages)
    cabal_packages = filter(StackTask.is_cabal, packages)

    yaml = 'flags: {}\n'

    if cabal_packages:
      yaml += 'packages:\n'
      for pkg in cabal_packages:
        path = pkg.path or os.path.join(get_buildroot(), pkg.target_base)
        yaml += '- ' + path + '\n'
    else:
      yaml += 'packages: []\n'

    if hackage_packages:
      yaml += 'extra-deps:\n'
      for pkg in hackage_packages:
        yaml += '- ' + pkg.package + '-' + pkg.version + '\n'
    else:
      yaml += 'extra-deps: []\n'

    yaml += 'resolver: ' + target.resolver + '\n'

    return yaml

  def stack_task(self, command, vt, extra_args = []):
    """
    This function provides shared logic for all `StackTask` sub-classes, which
    consists of:

    * creating a `stack.yaml` file within that target's cached results directory
    * invoking `stack` from within that directory

    Any executables generated by the `stack` command will be stored in a `bin/`
    subdirectory of the cached results directory
    """
    yaml = StackTask.make_stack_yaml(vt.target)

    stack_yaml_path = os.path.join(vt.results_dir, 'stack.yaml')
    with open(stack_yaml_path, 'w') as handle:
      handle.write(yaml)

    bin_path = os.path.join(vt.results_dir, 'bin')
    safe_mkdir(bin_path)

    args = [
      'stack',
      '--verbosity', 'error',
      '--local-bin-path', bin_path,
      '--install-ghc',
      '--stack-yaml=' + stack_yaml_path,
      command,
      vt.target.package
    ] + extra_args

    try:
      with self.context.new_workunit(name='stack-run', labels=[WorkUnitLabel.TOOL]) as workunit:
        subprocess.check_call(args)
    except subprocess.CalledProcessError:
      raise TaskError('''
`stack` subprocess failed with the following inputs:

Arguments: {args}
Contents of {stack_yaml_path}:

```
{yaml}
```
'''.strip().format(stack_yaml_path=stack_yaml_path,
                   yaml=yaml,
                   args=args))
      raise

  @abstractmethod
  def execute(self):
    pass
