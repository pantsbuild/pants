# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
from collections import OrderedDict, defaultdict

from twitter.common.collections import OrderedSet

from pants.base.address import Address
from pants.base.address_lookup_error import AddressLookupError
from pants.base.build_configuration import BuildConfiguration
from pants.base.build_file import FilesystemBuildFile
from pants.base.build_file_address_mapper import BuildFileAddressMapper
from pants.base.build_file_parser import BuildFileParser


logger = logging.getLogger(__name__)


class MyBuildGraph(object):
  """A directed acyclic graph of Targets and dependencies. Not necessarily connected."""

  # class DuplicateAddressError(AddressLookupError):
  #   """The same address appears multiple times in a dependency list"""
  #
  # class TransitiveLookupError(AddressLookupError):
  #   """Used to append the current node to the error message from an AddressLookupError """

  def __init__(self, address_mapper):
    self._address_mapper = address_mapper

  def reset(self):
    """Clear out the state of the BuildGraph, in particular Target mappings and dependencies."""
    self._addresses_already_closed = set()
    self._target_by_address = OrderedDict()
    self._target_dependencies_by_address = defaultdict(OrderedSet)
    self._target_dependees_by_address = defaultdict(set)
    # self._derived_from_by_derivative_address = {}

  # Rule 1:
  # Target is responsible for keeping track of its direct dependencies
  # and for registering itself as a dependee for them.
  # Rule 2:
  # Target is not responsible for keeping track of its direct dependees
  # nor for registering itself as a dependency for them.

  def update(self, address, target):
    """Update or create if non-existing."""
    if address in self._target_by_address:
      # Hmm, the target is already here. Maybe dependencies have updated?
      self.delete(address)

    # Reassign to a new instance.
    self._target_by_address[address] = target

    # Add dependencies anew.
    for dependency in target.dependencies:
      self._target_dependencies_by_address[address].add(dependency)
      self._target_dependees_by_address[dependency].add(address)

  def delete(self, address):
    if address in self._target_by_address:
      target = self._target_by_address[address]
      self.delete_existing_dependencies(address, target.dependencies)
      self._target_by_address[address] = None
    else:
      # Whoa, trying to delete non-existing target. That's bad.
      raise AddressLookupError

  def delete_existing_dependencies(self, address, dependencies):
    for dependency in dependencies:
      self._target_dependencies_by_address[address].remove(dependency)
      self._target_dependees_by_address[dependency].remove(address)


def is_build_file(filepath):
  return filepath.basename.startswith("BUILD")


def is_empty_file(filepath):
  return os.path.getsize(filepath) == 0


def infer_address_prefix_from_build_file_location(relative_build_file_path):
  pass


class MyBuildGraphServer(object):

  def __init__(self):
    root_dir = "..."
    build_file_parser = BuildFileParser(BuildConfiguration(), root_dir)
    build_file_type = FilesystemBuildFile
    self.build_graph = MyBuildGraph(BuildFileAddressMapper(build_file_parser, build_file_type))

  # Here go all possible file events
  def file_created(self, filepath):
    if is_build_file(filepath):
      # BUILD file was just created.
      if is_empty_file(filepath):
        # Nothing to do.
        pass
      else:
        # There is some content in this BUILD file.
        targets = parse_targets_from_build_file(filepath)
        for target in targets:
          self.build_graph.update(compute_address_for_target(target), target)


  def file_deleted(self):
    if is_build_file(filepath):
      # BUILD file was just deleted.

      # All targets from there should be now deleted.
      # Get all addresses that were in this file. Infer them from filename?
      addresses = infer_addresses_from_build_file_location(filepath)

      for address in addresses:
          self.build_graph.delete(address)

  def file_renamed(self):
    # TODO: if is build file then check that it's still named as build file?
    pass

  def file_changed(self):
    # TODO: remove all existing targets with corresponding prefix
    # TODO: then add all targets as if file was new
    pass

  def directory_renamed(self):
    # TODO: Iterate overall BUILD files in there. Their address has been changed.
    # TODO: Therefore, delete the old nodes, create the new nodes.
    pass

  def directory_deleted(self):
    # TODO: Iterate over all BUILD files in there. But they are non-existing!
    pass
