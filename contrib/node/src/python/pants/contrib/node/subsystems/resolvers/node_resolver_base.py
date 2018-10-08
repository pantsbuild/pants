# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import re
import shutil
from abc import abstractmethod

from pants.base.build_environment import get_buildroot
from pants.util.dirutil import safe_mkdir
from pants.util.meta import AbstractClass


class NodeResolverBase(AbstractClass):

  file_regex = re.compile('^file:(.*)$')

  @abstractmethod
  def resolve_target(self, node_task, target, results_dir, node_paths, resolve_locally=False, **kwargs):
    """Resolve a NodePackage target."""

  @classmethod
  def prepare(cls, options, round_manager):
    """Allows a resolver to add additional product requirements to the NodeResolver task."""
    pass

  @classmethod
  def parse_file_path(cls, file_path):
    """Parse a file address path without the file specifier"""
    address = None
    pattern = cls.file_regex.match(file_path)
    if pattern:
      address = pattern.group(1)
    return address

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

  def _get_target_from_package_name(self, target, package_name, file_path):
    """Get a dependent target given the package name and relative file path.

    This will only traverse direct dependencies of the passed target. It is not necessary
    to traverse further than that because transitive dependencies will be resolved under the
    direct dependencies and every direct dependencies is symlinked to the target.

    Returns `None` if the target does not exist.

    :param NodePackage target: A subclass of NodePackage
    :param string package_name: A package.json name that is required to be the same as the target name
    :param string file_path: Relative filepath from target to the package in the format 'file:<address_path>'
    """
    address_path = self.parse_file_path(file_path)
    if not address_path:
      return None

    dep_spec_path = os.path.normpath(os.path.join(target.address.spec_path, address_path))
    for dep in target.dependencies:
      if dep.package_name == package_name and dep.address.spec_path == dep_spec_path:
        return dep
    return None
