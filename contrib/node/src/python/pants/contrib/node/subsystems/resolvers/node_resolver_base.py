# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil
from abc import abstractmethod

from pants.base.build_environment import get_buildroot
from pants.util.dirutil import safe_mkdir
from pants.util.meta import AbstractClass


class NodeResolverBase(AbstractClass):
  @abstractmethod
  def resolve_target(self, node_task, target, results_dir, node_paths):
    """Resolve a NodePackage target."""

  @classmethod
  def prepare(cls, options, round_manager):
    """Allows a resolver to add additional product requirements to the NodeResolver task."""
    pass

  def _copy_sources(self, target, results_dir):
    """Copy sources from a target to a results directory.

    :param NodePackage target: A subclass of NodePackage
    :param string results_dir: The results directory
    """
    buildroot = get_buildroot()
    source_relative_to = target.address.spec_path
    for source in target.sources_relative_to_buildroot():
      dest = os.path.join(results_dir, os.path.relpath(source, source_relative_to))
      safe_mkdir(os.path.dirname(dest))
      shutil.copyfile(os.path.join(buildroot, source), dest)
