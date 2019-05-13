# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import re

from future.utils import text_type

from pants.backend.codegen.thrift.python.python_thrift_library import PythonThriftLibrary
from pants.base.specs import Specs
from pants.engine.fs import Digest, FileContent, FilesContent
from pants.engine.console import Console
from pants.engine.goal import Goal, LineOriented
from pants.engine.legacy.graph import HydratedTarget, HydratedTargets
from pants.engine.objects import Collection
from pants.engine.rules import console_rule, rule
from pants.engine.selectors import Get
from pants.util.collections_abc_backport import defaultdict
from pants.util.objects import datatype


logger = logging.getLogger(__name__)


# TODO: Move this up to a Validate() goal when there are more users.
class ValidatePythonThrift(LineOriented, Goal):

  name = 'validate-python-thrift'

  @classmethod
  def register_options(cls, register):
    super(ValidatePythonThrift, cls).register_options(register)
    # TODO: implement this for the @console_rule!!!
    register('--fail', type=bool, default=True, fingerprint=True,
             help='Whether to fail the build if validation fails.')


class ParsedNamespace(datatype([
    ('file_path', text_type),
    ('owning_target', HydratedTarget),
    ('py_thrift_namespace', text_type),
])): pass


ParsedNamespaces = Collection.of(ParsedNamespace)


@console_rule(ValidatePythonThrift, [Console, ValidatePythonThrift.Options, Specs])
def validate_python_thrift(console, options, specs):
  """???"""

  # raise NamespaceParseError('??')

  target_closure = yield Get(HydratedTargets, Specs, specs)
  # logger.debug('target_closure: {}'.format(target_closure))
  # raise Exception('target_closure: {}'.format(target_closure))
  all_parsed_namespaces = yield [Get(ParsedNamespaces, HydratedTarget, t) for t in target_closure]
  # raise Exception('all_parsed_namespaces: {}'.format(all_parsed_namespaces))
  unflattened_parsed_namespaces = [
    single_ns
    for namespace_set in all_parsed_namespaces
    for single_ns in namespace_set
  ]
  # logger.debug('unflattened_parsed_namespaces: {}'.format(unflattened_parsed_namespaces))
  raise Exception('unflattened_parsed_namespaces: {}'.format(unflattened_parsed_namespaces))

  # Check for any overlapping namespaces.
  namespaces_by_files = defaultdict(list)
  for parsed_namespace in unflattened_parsed_namespaces:
    path = parsed_namespace.file_path
    target = parsed_namespace.owning_target
    namespace = parsed_namespace.py_thrift_namespace
    namespaces_by_files[namespace].append((target, path))

  clashing_namespaces = {
    namespace: all_paths
    for namespace, all_paths in namespaces_by_files.items()
    if len(all_paths) > 1
  }

  with ValidatePythonThrift.line_oriented(options, console) as (_print_stdout, print_stderr):
    if clashing_namespaces:
      print_stderr('clashing namespaces for python thrift library sources detected in build graph:')

      for namespace, all_paths in clashing_namespaces.items():
        colliding = ', '.join('({}, {})'.format(t.address.spec, path) for (t, path) in all_paths)
        print_stderr('{}: [{}]'.format(namespace, colliding))
      yield ValidatePythonThrift(exit_code=1)
    else:
      print_stderr('success!')
      yield ValidatePythonThrift(exit_code=0)


py_namespace_pattern = re.compile(r'^namespace\s+py\s+([^\s]+)$', flags=re.MULTILINE)


class NamespaceParseError(Exception): pass


class ParseNamespaceRequest(datatype([
    ('target', HydratedTarget),
    ('file_content', FileContent),
])): pass


@rule(ParsedNamespace, [ParseNamespaceRequest])
def parse_py_thrift_namespace(parse_namespace_request):
  target = parse_namespace_request.target
  file_content = parse_namespace_request.file_content
  path = file_content.path
  # File content is provided as a binary string, so we have to decode it to search it.
  content = file_content.content.decode('utf-8')
  py_namespace_match = py_namespace_pattern.search(content)
  if py_namespace_match is None:
    # This debug log shows the contents of the file which failed to parse.
    logger.debug('failing thrift content from target {} in {} is:\n{}'
                 .format(target.address.spec, path, content))
    raise NamespaceParseError(
      "no python namespace (matching the pattern '{}') found in thrift source {} from target {}!"
      .format(py_namespace_pattern.pattern, path, target.address.spec))
  return ParsedNamespace(
    file_path=path,
    owning_target=target,
    py_thrift_namespace=py_namespace_match.group(1),
  )


@rule(ParsedNamespaces, [HydratedTarget])
def extract_py_thrift_namespaces(hydrated_target):
  import pdb; pdb.set_trace()
  if hydrated_target.adaptor.type_alias == PythonThriftLibrary.alias():
    sources_snapshot = hydrated_target.adaptor.sources.snapshot
    files_content = yield Get(FilesContent, Digest, sources_snapshot.directory_digest)
    all_parsed_namespaces = yield [Get(ParsedNamespace, ParseNamespaceRequest(hydrated_target, fc))
                                   for fc in files_content.dependencies]
  else:
    all_parsed_namespaces = []
  yield ParsedNamespaces(all_parsed_namespaces)


def rules():
  return [
    validate_python_thrift,
    parse_py_thrift_namespace,
    extract_py_thrift_namespaces,
  ]
