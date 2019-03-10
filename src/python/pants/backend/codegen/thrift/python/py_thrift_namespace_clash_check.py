# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import re
from builtins import str

from future.utils import text_type

from pants.backend.codegen.thrift.python.python_thrift_library import PythonThriftLibrary
from pants.base.exceptions import TaskError
from pants.engine.fs import Digest, FileContent, FilesContent
from pants.engine.legacy.graph import HydratedTarget
from pants.engine.objects import Collection
from pants.engine.rules import rule
from pants.engine.selectors import Get, Select
from pants.task.target_restriction_mixins import HasSkipOptionMixin
from pants.task.task import Task
from pants.util.collections_abc_backport import defaultdict
from pants.util.objects import datatype


logger = logging.getLogger(__name__)


class ParsedNamespace(datatype([
    ('file_path', text_type),
    ('owning_target', HydratedTarget),
    ('py_thrift_namespace', text_type),
])): pass


_ParsedNamespaces = Collection.of(ParsedNamespace)


_py_namespace_pattern = re.compile(r'^namespace\s+py\s+([^\s]+)$', flags=re.MULTILINE)


class _NamespaceParseError(Exception): pass


class ParseNamespaceRequest(datatype([
    ('target', HydratedTarget),
    ('file_content', FileContent),
])): pass


@rule(ParsedNamespace, [Select(ParseNamespaceRequest)])
def parse_py_thrift_namespace(parse_namespace_request):
  target = parse_namespace_request.target
  file_content = parse_namespace_request.file_content
  path = file_content.path
  # File content is provided as a binary string, so we have to decode it to search it.
  content = file_content.content.decode('utf-8')
  py_namespace_match = _py_namespace_pattern.search(content)
  if py_namespace_match is None:
    # This debug log shows the contents of the file which failed to parse.
    logger.debug('failing thrift content from target {} in {} is:\n{}'
                 .format(target.address.spec, path, content))
    raise _NamespaceParseError(
      "no python namespace (matching the pattern '{}') found in thrift source {} from target {}!"
      .format(_py_namespace_pattern.pattern, path, target.address.spec))
  return ParsedNamespace(
    file_path=path,
    owning_target=target,
    py_thrift_namespace=py_namespace_match.group(1),
  )


@rule(_ParsedNamespaces, [Select(HydratedTarget)])
def extract_py_thrift_namespaces(hydrated_target):
  if hasattr(hydrated_target.adaptor, 'sources'):
    sources_snapshot = hydrated_target.adaptor.sources.snapshot
    files_content = yield Get(FilesContent, Digest, sources_snapshot.directory_digest)
    all_parsed_namespaces = yield [Get(ParsedNamespace, ParseNamespaceRequest(hydrated_target, fc))
                                   for fc in files_content.dependencies]
  else:
    all_parsed_namespaces = []
  yield _ParsedNamespaces(all_parsed_namespaces)


class PyThriftNamespaceClashCheck(Task, HasSkipOptionMixin):
  """Check that no python thrift libraries in the build graph have files with clashing namespaces.

  This is a temporary workaround for https://issues.apache.org/jira/browse/THRIFT-515. A real fix
  would ideally be to extend Scrooge to support clashing namespaces with Python code. A second-best
  solution would be to check all *thrift* libraries in the build graph, but there is currently no
  "ThriftLibraryMixin" or other way to identify targets containing thrift code generically.
  """

  @classmethod
  def register_options(cls, register):
    super(PyThriftNamespaceClashCheck, cls).register_options(register)
    register('--skip', type=bool, default=False, fingerprint=True, recursive=True,
             help='Skip task.')

  @classmethod
  def product_types(cls):
    """Populate a dict mapping thrift sources to their namespaces and owning targets for testing."""
    return ['_py_thrift_namespaces_by_files']

  class NamespaceParseError(TaskError): pass

  class ClashingNamespaceError(TaskError): pass

  def execute(self):
    if self.skip_execution:
      return

    # Get file contents for python thrift library targets.
    py_thrift_targets = self.get_targets(lambda tgt: isinstance(tgt, PythonThriftLibrary))
    try:
      unflattened_parsed_namespaces = self.context._scheduler.product_request(
        _ParsedNamespaces,
        [t.address for t in py_thrift_targets],
      )
    except _NamespaceParseError as e:
      raise self.NamespaceParseError(str(e))

    # Check for any overlapping namespaces.
    namespaces_by_files = defaultdict(list)
    for all_parsed_namespaces in unflattened_parsed_namespaces:
      for parsed_namespace in all_parsed_namespaces.dependencies:
        path = parsed_namespace.file_path
        target = parsed_namespace.owning_target
        namespace = parsed_namespace.py_thrift_namespace
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
      raise self.ClashingNamespaceError(
        'clashing namespaces for python thrift library sources detected in build graph:\n{}'
        .format(pretty_printed_clashing))
    else:
      self.context.products.register_data('_py_thrift_namespaces_by_files', namespaces_by_files)


def rules():
  return [
    parse_py_thrift_namespace,
    extract_py_thrift_namespaces,
  ]
