# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.codegen.thrift.python.py_thrift_namespace_clash_check import \
  PyThriftNamespaceClashCheck
from pants.backend.codegen.thrift.python.python_thrift_library import PythonThriftLibrary
from pants_test.task_test_base import DeclarativeTaskTestMixin, TaskTestBase


class PyThriftNamespaceClashCheckTest(TaskTestBase, DeclarativeTaskTestMixin):

  @classmethod
  def task_type(cls):
    return PyThriftNamespaceClashCheck

  _target_specs = {
    'src/py-thrift:with-comments-and-other-namespaces' : {
      'target_type': PythonThriftLibrary,
      'sources': ['with-header.thrift'],
      'filemap': {
        'with-header.thrift': """\
// Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

namespace java org.pantsbuild.whatever
namespace py org.pantsbuild.py_whatever

struct A {}
""",
      },
    },

    'src/py-thrift:no-py-namespace': {
      'target_type': PythonThriftLibrary,
      'sources': ['bad.thrift'],
      'filemap': {
        'bad.thrift': """\
#namespace scala org.pantsbuild.whatever
namespace java org.pantsbuild.whatever

struct A {}
""",
      },
    },

    'src/py-thrift:clashing-namespace': {
      'target_type': PythonThriftLibrary,
      'sources': ['a.thrift', 'b.thrift'],
      'filemap': {
        'a.thrift': """\
namespace py org.pantsbuild.namespace

struct A {}
""",
        'b.thrift': """\
namespace py org.pantsbuild.namespace

struct B {}
""",
      },
    },

    'src/py-thrift-clashing:clashingA': {
      'target_type': PythonThriftLibrary,
      'sources': ['a.thrift'],
      'filemap': {
        'a.thrift': """\
namespace py org.pantsbuild.namespace

struct A {}
""",
      },
    },

    'src/py-thrift-clashing:clashingB': {
      'target_type': PythonThriftLibrary,
      'sources': ['b.thrift'],
      'filemap': {
        'b.thrift': """\
namespace py org.pantsbuild.namespace

struct B {}
""",
      },
    }
  }

  def target_dict(self):
    return self.populate_target_dict(self._target_specs)

  _exception_prelude = """\
Clashing namespaces for python thrift library sources detected in build graph. This will silently
overwrite previously generated python sources with generated sources from thrift files declaring the
same python namespace. This is an upstream WONTFIX in thrift, see:
      https://issues.apache.org/jira/browse/THRIFT-515

Use --test_scope-skip to avoid this check if this breaks your existing build.
Errors:"""

  def test_no_py_namespace(self):
    no_py_namespace_target = self.target_dict()['no-py-namespace']
    with self.assertRaisesWithMessage(PyThriftNamespaceClashCheck.NamespaceParseError, """\
no python namespace (matching the pattern '^namespace\s+py\s+([^\s]+)$') \
found in thrift source src/py-thrift/bad.thrift from target src/py-thrift:no-py-namespace!"""):
      self.invoke_tasks(target_roots=[no_py_namespace_target])

  def test_clashing_namespace_same_target(self):
    clashing_same_target = self.target_dict()['clashing-namespace']
    with self.assertRaisesWithMessage(PyThriftNamespaceClashCheck.ClashingNamespaceError, """{}
org.pantsbuild.namespace: [(src/py-thrift:clashing-namespace, src/py-thrift/a.thrift), (src/py-thrift:clashing-namespace, src/py-thrift/b.thrift)]
""".format(self._exception_prelude)):
      self.invoke_tasks(target_roots=[clashing_same_target])

  def test_clashing_namespace_multiple_targets(self):
    target_dict = self.target_dict()
    clashing_targets = [target_dict[k] for k in ['clashingA', 'clashingB']]
    with self.assertRaisesWithMessage(PyThriftNamespaceClashCheck.ClashingNamespaceError, """{}
org.pantsbuild.namespace: [(src/py-thrift-clashing:clashingA, src/py-thrift-clashing/a.thrift), (src/py-thrift-clashing:clashingB, src/py-thrift-clashing/b.thrift)]
""".format(self._exception_prelude)):
      self.invoke_tasks(target_roots=clashing_targets)

  def test_accepts_py_namespace_with_comments_above(self):
    commented_thrift_source_target = self.target_dict()['with-comments-and-other-namespaces']
    result = self.invoke_tasks(target_roots=[commented_thrift_source_target])
    # Check that the file was correctly mapped to the namespace parsed out of its file content.
    namespaces_by_files = result.context.products.get_data('_py_thrift_namespaces_by_files')
    self.assertEqual(
      [('org.pantsbuild.py_whatever', [
        (commented_thrift_source_target, 'src/py-thrift/with-header.thrift'),
      ])],
      list(namespaces_by_files.items()))
