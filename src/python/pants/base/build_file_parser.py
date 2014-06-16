# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import logging
import traceback
from collections import defaultdict
from functools import partial

from twitter.common.lang import Compatibility

from pants.base.address import BuildFileAddress, parse_spec, SyntheticAddress
from pants.base.build_file import BuildFile
from pants.base.exceptions import TargetDefinitionException


logger = logging.getLogger(__name__)


class TargetProxy(object):
  def __init__(self, target_type, build_file, args, kwargs):
    if 'name' not in kwargs:
      raise ValueError('name is a required parameter to all Target objects'
                       ' specified within a BUILD file.'
                       '  Target type was: {target_type}.'
                       '  Current BUILD file is: {build_file}.'
                       .format(target_type=target_type,
                               build_file=build_file))

    if args:
      raise ValueError('All arguments passed to Targets within BUILD files should'
                       ' use explicit keyword syntax.'
                       '  Target type was: {target_type}.'
                       '  Current BUILD file is: {build_file}.'
                       '  Arguments passed were: {args}'
                       .format(target_type=target_type,
                               build_file=build_file,
                               args=args))

    if 'build_file' in kwargs:
      raise ValueError('build_file cannot be passed as an explicit argument to a'
                       ' target within a BUILD file.'
                       '  Target type was: {target_type}.'
                       '  Current BUILD file is: {build_file}.'
                       '  build_file argument passed was: {build_file_arg}'
                       .format(target_type=target_type,
                               build_file=build_file,
                               build_file_arg=kwargs.get('build_file')))

    self.target_type = target_type
    self.build_file = build_file
    self.kwargs = kwargs
    self.name = kwargs['name']
    self.address = BuildFileAddress(build_file, self.name)
    self.description = None

    self.dependencies = self.kwargs.pop('dependencies', [])
    self._dependency_addresses = None
    for dep_spec in self.dependencies:
      if not isinstance(dep_spec, Compatibility.string):
        msg = ('dependencies passed to Target constructors must be strings.  {dep_spec} is not'
               ' a string.  Target type was: {target_type}.  Current BUILD file is: {build_file}.'
               .format(target_type=target_type, build_file=build_file, dep_spec=dep_spec))
        raise TargetDefinitionException(target=self, msg=msg)

  @property
  def dependency_addresses(self):
    def dep_address_iter():
      for dep_spec in self.dependencies:
        dep_spec_path, dep_target_name = parse_spec(dep_spec,
                                                    relative_to=self.build_file.spec_path)
        dep_build_file = BuildFileCache.spec_path_to_build_file(self.build_file.root_dir,
                                                                dep_spec_path)
        dep_address = BuildFileAddress(dep_build_file, dep_target_name)
        yield dep_address

    if self._dependency_addresses is None:
      self._dependency_addresses = list(dep_address_iter())
    return self._dependency_addresses

  def with_description(self, description):
    self.description = description

  def to_target(self, build_graph):
    try:
      return self.target_type(build_graph=build_graph,
                              address=self.address,
                              **self.kwargs).with_description(self.description)
    except Exception:
      traceback.print_exc()
      logger.exception('Failed to instantiate Target with type {target_type} with name "{name}"'
                       ' from {build_file}'
                       .format(target_type=self.target_type,
                               name=self.name,
                               build_file=self.build_file))
      raise

  def __str__(self):
    format_str = ('<TargetProxy(target_type={target_type}, build_file={build_file})'
                  ' [name={name}, address={address}]>')
    return format_str.format(target_type=self.target_type,
                             build_file=self.build_file,
                             name=self.name,
                             address=self.address)

  def __repr__(self):
    format_str = 'TargetProxy(target_type={target_type}, build_file={build_file}, kwargs={kwargs})'
    return format_str.format(target_type=self.target_type,
                             build_file=self.build_file,
                             kwargs=self.kwargs)


class TargetCallProxy(object):
  def __init__(self, target_type, build_file, registered_target_proxies):
    self._target_type = target_type
    self._build_file = build_file
    self._registered_target_proxies = registered_target_proxies

  def __call__(self, *args, **kwargs):
    target_proxy = TargetProxy(self._target_type, self._build_file, args, kwargs)
    self._registered_target_proxies.add(target_proxy)
    return target_proxy

  def __repr__(self):
    return ('<TargetCallProxy(target_type={target_type}, build_file={build_file},'
            ' registered_target_proxies=<dict with id: {registered_target_proxies_id}>)>'
            .format(target_type=self._target_type,
                    build_file=self._build_file,
                    registered_target_proxies_id=id(self._registered_target_proxies)))


class BuildFileCache(object):
  """A little cache for BuildFiles.
  They are mildly expensive to construct since they actually peek
  at the filesystem in their __init__.  This adds up when translating specs to addresses.
  """

  _spec_path_to_build_file_cache = {}

  @classmethod
  def spec_path_to_build_file(cls, root_dir, spec_path):
    if (root_dir, spec_path) not in cls._spec_path_to_build_file_cache:
      cls._spec_path_to_build_file_cache[(root_dir, spec_path)] = BuildFile(root_dir, spec_path)
    return cls._spec_path_to_build_file_cache[(root_dir, spec_path)]

  @classmethod
  def clear(cls):
    cls._spec_path_to_build_file_cache = {}


class BuildFileParser(object):

  class TargetConflictException(Exception):
    """Thrown if the same target is redefined in a BUILD file"""

  class SiblingConflictException(Exception):
    """Thrown if the same target is redefined in another BUILD file in the same directory"""

  def clear_registered_context(self):
    self._exposed_objects = {}
    self._partial_path_relative_utils = {}
    self._applicative_path_relative_utils = {}
    self._target_alias_map = {}
    self._target_creation_utils = {}

  def report_registered_context(self):
    """Return dict of syms defined in BUILD files, useful for docs/help.

    This dict isn't so useful for actually parsing BUILD files.
    It's useful for generating things like
    http://pantsbuild.github.io/build_dictionary.html
    """
    retval = {}
    retval.update(self._exposed_objects)
    retval.update(self._partial_path_relative_utils)
    retval.update(self._applicative_path_relative_utils)
    retval.update(self._target_alias_map)
    return retval

  def report_target_aliases(self):
    return self._target_alias_map.copy()

  def register_alias_groups(self, alias_map):
    for alias, obj in alias_map.get('exposed_objects', {}).items():
      self.register_exposed_object(alias, obj)

    for alias, obj in alias_map.get('applicative_path_relative_utils', {}).items():
      self.register_applicative_path_relative_util(alias, obj)

    for alias, obj in alias_map.get('partial_path_relative_utils', {}).items():
      self.register_partial_path_relative_util(alias, obj)

    for alias, obj in alias_map.get('target_aliases', {}).items():
      self.register_target_alias(alias, obj)

    for alias, func in alias_map.get('target_creation_utils', {}).items():
      self.register_target_creation_utils(alias, func)

  # TODO(pl): For the next four methods, provide detailed documentation.  Especially for the middle
  # two, the semantics are slightly tricky.
  def register_exposed_object(self, alias, obj):
    if alias in self._exposed_objects:
      logger.warn('Object alias {alias} has already been registered.  Overwriting!'
                  .format(alias=alias))
    self._exposed_objects[alias] = obj

  def register_applicative_path_relative_util(self, alias, obj):
    if alias in self._applicative_path_relative_utils:
      logger.warn('Applicative path relative util alias {alias} has already been registered.'
                  '  Overwriting!'
                  .format(alias=alias))
    self._applicative_path_relative_utils[alias] = obj

  def register_partial_path_relative_util(self, alias, obj):
    if alias in self._partial_path_relative_utils:
      logger.warn('Partial path relative util alias {alias} has already been registered.'
                  '  Overwriting!'
                  .format(alias=alias))
    self._partial_path_relative_utils[alias] = obj

  def register_target_alias(self, alias, obj):
    if alias in self._target_alias_map:
      logger.warn('Target alias {alias} has already been registered.  Overwriting!'
                  .format(alias=alias))
    self._target_alias_map[alias] = obj

  def register_target_creation_utils(self, alias, func):
    if alias in self._target_creation_utils:
      logger.warn('Target Creation alias {alias} has already been registered.  Overwriting!'
                  .format(alias=alias))
    self._target_creation_utils[alias] = func

  def __init__(self, root_dir, run_tracker=None):
    self._root_dir = root_dir
    self.run_tracker = run_tracker

    self.clear_registered_context()

    self._target_proxy_by_address = {}
    self._target_proxies_by_build_file = defaultdict(set)
    self._added_build_files = set()
    self._added_build_file_families = set()

    self.addresses_by_build_file = defaultdict(set)

  def inject_address_into_build_graph(self, address, build_graph):
    self._populate_target_proxy_for_address(address)
    target_proxy = self._target_proxy_by_address[address]

    if not build_graph.contains_address(address):
      target = target_proxy.to_target(build_graph)
      build_graph.inject_target(target)

  def inject_address_closure_into_build_graph(self,
                                              address,
                                              build_graph,
                                              addresses_already_closed=None):
    addresses_already_closed = addresses_already_closed or set()

    if address in addresses_already_closed:
      return

    self._populate_target_proxy_transitive_closure_for_address(address)
    target_proxy = self._target_proxy_by_address[address]

    if not build_graph.contains_address(address):
      addresses_already_closed.add(address)
      for dep_address in target_proxy.dependency_addresses:
        self.inject_address_closure_into_build_graph(dep_address,
                                                     build_graph,
                                                     addresses_already_closed)
      target = target_proxy.to_target(build_graph)
      build_graph.inject_target(target, dependencies=target_proxy.dependency_addresses)

      for traversable_spec in target.traversable_dependency_specs:
        spec_path, target_name = parse_spec(traversable_spec, relative_to=address.spec_path)
        self._inject_spec_closure_into_build_graph(spec_path,
                                                   target_name,
                                                   build_graph,
                                                   addresses_already_closed)
        traversable_spec_target = build_graph.get_target(SyntheticAddress(spec_path, target_name))
        if traversable_spec_target not in target.dependencies:
          build_graph.inject_dependency(dependent=target.address,
                                        dependency=traversable_spec_target.address)
          target.mark_transitive_invalidation_hash_dirty()

      for traversable_spec in target.traversable_specs:
        spec_path, target_name = parse_spec(traversable_spec, relative_to=address.spec_path)
        self._inject_spec_closure_into_build_graph(spec_path,
                                                   target_name,
                                                   build_graph,
                                                   addresses_already_closed)
        target.mark_transitive_invalidation_hash_dirty()

  def inject_spec_closure_into_build_graph(self, spec, build_graph, addresses_already_closed=None):
    spec_path, target_name = parse_spec(spec)
    self._inject_spec_closure_into_build_graph(spec_path,
                                               target_name,
                                               build_graph,
                                               addresses_already_closed)

  def _inject_spec_closure_into_build_graph(self,
                                            spec_path,
                                            target_name,
                                            build_graph,
                                            addresses_already_closed=None):
    addresses_already_closed = addresses_already_closed or set()
    build_file = BuildFileCache.spec_path_to_build_file(self._root_dir, spec_path)
    address = BuildFileAddress(build_file, target_name)
    self.inject_address_closure_into_build_graph(address, build_graph, addresses_already_closed)

  def _populate_target_proxy_for_address(self, address):
    self.parse_build_file_family(address.build_file)

    if address not in self._target_proxy_by_address:
      raise ValueError('{address} from spec {spec} was not found in BUILD file {build_file}.'
                       .format(address=address,
                               spec=address.spec,
                               build_file=address.build_file))

    target_proxy = self._target_proxy_by_address[address]

  def _populate_target_proxy_transitive_closure_for_address(self,
                                                            address,
                                                            addresses_already_closed=None):
    """Recursively parse the BUILD files transitively referred to by `address`.
    Note that `address` must be a BuildFileAddress, not a SyntheticAddress.
    From each parsed BUILD file, TargetProxy objects are generated.  For the TargetProxies
    that are dependencies of the root address to close over, recursively parse their dependency
    addresses.
    This method is immune to cycles between either BUILD files or individual Targets, but it is
    also incapable of detecting them.
    """

    addresses_already_closed = addresses_already_closed or set()

    if address in addresses_already_closed:
      return

    self.parse_build_file_family(address.build_file)

    if address not in self._target_proxy_by_address:
      raise ValueError('{address} from spec {spec} was not found in BUILD file {build_file}.'
                       .format(address=address,
                               spec=address.spec,
                               build_file=address.build_file))

    target_proxy = self._target_proxy_by_address[address]
    addresses_already_closed.add(address)

    for dep_address in target_proxy.dependency_addresses:
      if dep_address not in addresses_already_closed:
        self._populate_target_proxy_transitive_closure_for_address(dep_address,
                                                                   addresses_already_closed)

  def parse_build_file_family(self, build_file):
    if build_file not in self._added_build_file_families:
      for bf in build_file.family():
        self.parse_build_file(bf)
    self._added_build_file_families.add(build_file)

  def parse_build_file(self, build_file):
    """Capture TargetProxies from parsing `build_file`.
    Prepare a context for parsing, read a BUILD file from the filesystem, and record the
    TargetProxies generated by executing the code.
    """

    if build_file in self._added_build_files:
      logger.debug('BuildFile {build_file} has already been parsed.'
                   .format(build_file=build_file))
      return

    logger.debug("Parsing BUILD file {build_file}."
                 .format(build_file=build_file))

    parse_context = {}

    # TODO(pl): Don't inject __file__ into the context.  BUILD files should not be aware
    # of their location on the filesystem.
    parse_context['__file__'] = build_file.full_path

    parse_context.update(self._exposed_objects)
    parse_context.update(
      (key, partial(util, rel_path=build_file.spec_path)) for
      key, util in self._partial_path_relative_utils.items()
    )
    parse_context.update(
      (key, util(rel_path=build_file.spec_path)) for
      key, util in self._applicative_path_relative_utils.items()
    )
    registered_target_proxies = set()
    parse_context.update(
      (alias, TargetCallProxy(target_type=target_type,
                              build_file=build_file,
                              registered_target_proxies=registered_target_proxies)) for
      alias, target_type in self._target_alias_map.items()
    )

    for key, func in self._target_creation_utils.items():
      parse_context.update({key: partial(func, alias_map=parse_context)})

    try:
      build_file_code = build_file.code()
    except Exception:
      logger.exception("Error parsing {build_file}."
                       .format(build_file=build_file))
      traceback.print_exc()
      raise

    try:
      Compatibility.exec_function(build_file_code, parse_context)
    except Exception:
      logger.exception("Error running {build_file}."
                       .format(build_file=build_file))
      traceback.print_exc()
      raise

    for target_proxy in registered_target_proxies:
      logger.debug('Adding {target_proxy} to the proxy build graph with {address}'
                   .format(target_proxy=target_proxy,
                           address=target_proxy.address))

      if target_proxy.address in self._target_proxy_by_address:
        conflicting_target = self._target_proxy_by_address[target_proxy.address]
        if (conflicting_target.address.build_file != target_proxy.address.build_file):
          raise BuildFileParser.SiblingConflictException(
            "Both {conflicting_file} and {target_file} define the same target '{target_name}'"
            .format(conflicting_file=conflicting_target.address.build_file,
                    target_file=target_proxy.address.build_file,
                    target_name=conflicting_target.address.target_name))
        raise BuildFileParser.TargetConflictException(
          "File {conflicting_file} defines target '{target_name}' more than once."
          .format(conflicting_file=conflicting_target.address.build_file,
                  target_name=conflicting_target.address.target_name))

      assert target_proxy.address not in self.addresses_by_build_file[build_file], (
        '{address} has already been associated with {build_file} in the build graph.'
        .format(address=target_proxy.address,
                build_file=build_file))

      self._target_proxy_by_address[target_proxy.address] = target_proxy
      self.addresses_by_build_file[build_file].add(target_proxy.address)
      self._target_proxies_by_build_file[build_file].add(target_proxy)
    self._added_build_files.add(build_file)

    logger.debug("{build_file} produced the following TargetProxies:"
                 .format(build_file=build_file))
    for target_proxy in registered_target_proxies:
      logger.debug("  * {target_proxy}".format(target_proxy=target_proxy))
