# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import re
from builtins import zip

from pants.backend.codegen.thrift.python.python_thrift_library import PythonThriftLibrary
from pants.base.exceptions import TaskError
from pants.engine.fs import FilesContent
from pants.task.target_restriction_mixins import HasSkipOptionMixin
from pants.task.task import Task
from pants.util.collections_abc_backport import OrderedDict, defaultdict


class PyThriftNamespaceClashCheck(Task, HasSkipOptionMixin):
  """Check that no python thrift libraries in the build graph have files with clashing namespaces.

  This is a temporary workaround for https://issues.apache.org/jira/browse/THRIFT-515. A real fix
  would ideally be to extend Scrooge to support clashing namespaces with Python code. A second-best
  solution would be to check all *thrift* libraries in the build graph, but there is currently no
  "ThriftLibraryMixin" or other way to identify targets containing thrift code generically.
  """
  # This scope is set for testing only.
  options_scope = 'py-thrift-namespace-clash-check'

  @classmethod
  def register_options(cls, register):
    super(PyThriftNamespaceClashCheck, cls).register_options(register)
    register('--skip', type=bool, default=False, fingerprint=True, recursive=True,
             help='Skip task.')

  @classmethod
  def product_types(cls):
    """Populate a dict mapping thrift sources to their namespaces and owning targets for testing."""
    return ['_py_thrift_namespaces_by_files']

  _py_namespace_pattern = re.compile(r'^namespace\s+py\s+([^\s]+)$', flags=re.MULTILINE)

  class NamespaceParseError(TaskError): pass

  def _extract_py_namespace_from_content(self, target, thrift_filename, thrift_source_content):
    py_namespace_match = self._py_namespace_pattern.search(thrift_source_content)
    if py_namespace_match is None:
      self.context.log.debug('failing thrift content is:\n{}'.format(thrift_source_content))
      raise self.NamespaceParseError(
        "no python namespace (matching the pattern '{}') found in thrift source {} from target {}!"
        .format(self._py_namespace_pattern.pattern,
                thrift_filename,
                target.address.spec))
    return py_namespace_match.group(1)

  class ClashingNamespaceError(TaskError): pass

  def execute(self):
    if self.skip_execution:
      return

    # Get file contents for python thrift library targets.
    py_thrift_targets = self.get_targets(lambda tgt: isinstance(tgt, PythonThriftLibrary))
    target_snapshots = OrderedDict(
      (t, t.sources_snapshot(scheduler=self.context._scheduler).directory_digest)
      for t in py_thrift_targets)
    filescontent_by_target = OrderedDict(zip(
      target_snapshots.keys(),
      self.context._scheduler.product_request(FilesContent, target_snapshots.values())))
    thrift_file_sources_by_target = OrderedDict(
      (t, [(file_content.path, file_content.content) for file_content in all_content.dependencies])
      for t, all_content in filescontent_by_target.items())

    # Extract the python namespace from each thrift source file.
    py_namespaces_by_target = OrderedDict(
      (t, [
        # File content is provided as a binary string, so we have to decode it.
        (path, self._extract_py_namespace_from_content(t, path, content.decode('utf-8')))
        for (path, content) in all_content
      ])
      for t, all_content in thrift_file_sources_by_target.items()
    )

    # Check for any overlapping namespaces.
    namespaces_by_files = defaultdict(list)
    for target, all_namespaces in py_namespaces_by_target.items():
      for (path, namespace) in all_namespaces:
        namespaces_by_files[namespace].append((target, path))

    clashing_namespaces = {
      namespace: all_paths
      for namespace, all_paths in namespaces_by_files.items()
      if len(all_paths) > 1
    }
    if clashing_namespaces:
      pretty_printed_clashing = '\n'.join(
        '{}: [{}]'
        .format(
          namespace,
          ', '.join('({}, {})'.format(t.address.spec, path) for (t, path) in all_paths)
        )
        for namespace, all_paths in clashing_namespaces.items()
      )
      raise self.ClashingNamespaceError("""\
Clashing namespaces for python thrift library sources detected in build graph. This will silently
overwrite previously generated python sources with generated sources from thrift files declaring the
same python namespace. This is an upstream WONTFIX in thrift, see:
      https://issues.apache.org/jira/browse/THRIFT-515

Use --{}-skip to avoid this check if this breaks your existing build.
Errors:
{}
""".format(self.get_options_scope_equivalent_flag_component(), pretty_printed_clashing))
    else:
      self.context.products.register_data('_py_thrift_namespaces_by_files', namespaces_by_files)
