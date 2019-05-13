# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from textwrap import dedent

from pants.backend.codegen.thrift.python.py_thrift_namespace_clash_check import \
  NamespaceParseError, ValidatePythonThrift
from pants.backend.codegen.thrift.python.py_thrift_namespace_clash_check import \
  rules as namespace_clash_rules
from pants.backend.codegen.thrift.python.python_thrift_library import PythonThriftLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants_test.console_rule_test_base import ConsoleRuleTestBase


class PyThriftNamespaceClashCheckTest(ConsoleRuleTestBase):
  goal_cls = ValidatePythonThrift

  @classmethod
  def rules(cls):
    return super(PyThriftNamespaceClashCheckTest, cls).rules() + namespace_clash_rules()

  @classmethod
  def alias_groups(cls):
    return BuildFileAliases(
      targets={
        PythonThriftLibrary.alias(): PythonThriftLibrary,
      }
    )

  def setUp(self):
    super(PyThriftNamespaceClashCheckTest, self).setUp()

    # ???
    self.create_file('src/py-thrift/with-header.thrift', dedent("""\
      // Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
      // Licensed under the Apache License, Version 2.0 (see LICENSE).

      namespace java org.pantsbuild.whatever
      namespace py org.pantsbuild.py_whatever

      struct A {}
      """))
    self.add_to_build_file('src/py-thrift/BUILD', dedent("""\
      python_thrift_library(
        name='with-comments-and-other-namespaces',
        sources=['with-header.thrift'],
      )
      """))

    self.create_file('src/py-thrift/bad.thrift', dedent("""\
      #@namespace scala org.pantsbuild.whatever
      namespace java org.pantsbuild.whatever

      struct A {}
      """))
    self.add_to_build_file('src/py-thrift/BUILD', dedent("""\
      python_thrift_library(
        name='no-py-namespace',
        sources=['bad.thrift'],
      )
      """))

  _target_specs = {
    # 'src/py-thrift:with-comments-and-other-namespaces' : {
    #   'target_type': PythonThriftLibrary,
    #   'sources': ['with-header.thrift'],
    #   'filemap': {
    #     'with-header.thrift': dedent("""\
    #       // Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
    #       // Licensed under the Apache License, Version 2.0 (see LICENSE).

    #       namespace java org.pantsbuild.whatever
    #       namespace py org.pantsbuild.py_whatever

    #       struct A {}
    #       """),
    #   },
    # },

    # 'src/py-thrift:no-py-namespace': {
    #   'target_type': PythonThriftLibrary,
    #   'sources': ['bad.thrift'],
    #   'filemap': {
    #     'bad.thrift': dedent("""\
    #       #@namespace scala org.pantsbuild.whatever
    #       namespace java org.pantsbuild.whatever

    #       struct A {}
    #       """),
    #   },
    # },

    'src/py-thrift:clashing-namespace': {
      'target_type': PythonThriftLibrary,
      'sources': ['a.thrift', 'b.thrift'],
      'filemap': {
        'a.thrift': dedent("""\
          namespace py org.pantsbuild.namespace

          struct A {}
          """),
        'b.thrift': dedent("""\
          namespace py org.pantsbuild.namespace

          struct B {}
          """),
      },
    },

    'src/py-thrift-clashing:clashingA': {
      'target_type': PythonThriftLibrary,
      'sources': ['a.thrift'],
      'filemap': {
        'a.thrift': dedent("""\
          namespace py org.pantsbuild.namespace

          struct A {}
          """),
      },
    },

    'src/py-thrift-clashing:clashingB': {
      'target_type': PythonThriftLibrary,
      'sources': ['b.thrift'],
      'filemap': {
        'b.thrift': dedent("""\
          namespace py org.pantsbuild.namespace

          struct B {}
          """),
      },
    }
  }

  def _target_dict(self):
    return self.populate_target_dict(self._target_specs)

  def _run_tasks(self, target_roots):
    self.set_options(strict=True)
    return self.invoke_tasks(target_roots=target_roots)

  _exception_prelude = """\
Clashing namespaces for python thrift library sources detected in build graph. This will silently
overwrite previously generated python sources with generated sources from thrift files declaring the
same python namespace. This is an upstream WONTFIX in thrift, see:
      https://issues.apache.org/jira/browse/THRIFT-515
Errors:"""

  def test_no_py_namespace(self):
    self.maxDiff = None
    self.assert_console_raises_with_message(
      NamespaceParseError,
      execution_error=True,
      args=['src/py-thrift:no-py-namespace'],
      exc_message=dedent("""\
        no python namespace (matching the pattern '^namespace\s+py\s+([^\s]+)$') found in thrift source src/py-thrift/bad.thrift from target src/py-thrift:no-py-namespace!"""))

  def test_clashing_namespace_same_target(self):
    clashing_same_target = self._target_dict()['clashing-namespace']
    with self.assertRaisesWithMessage(Exception, """{}
org.pantsbuild.namespace: [(src/py-thrift:clashing-namespace, src/py-thrift/a.thrift), (src/py-thrift:clashing-namespace, src/py-thrift/b.thrift)]
""".format(self._exception_prelude)):
      self._run_tasks(target_roots=[clashing_same_target])

  def test_clashing_namespace_multiple_targets(self):
    target_dict = self._target_dict()
    clashing_targets = [target_dict[k] for k in ['clashingA', 'clashingB']]
    with self.assertRaisesWithMessage(Exception, """{}
org.pantsbuild.namespace: [(src/py-thrift-clashing:clashingA, src/py-thrift-clashing/a.thrift), (src/py-thrift-clashing:clashingB, src/py-thrift-clashing/b.thrift)]
""".format(self._exception_prelude)):
      self._run_tasks(target_roots=clashing_targets)

  def test_accepts_py_namespace_with_comments_above(self):
    commented_thrift_source_target = self._target_dict()['with-comments-and-other-namespaces']
    result = self._run_tasks(target_roots=[commented_thrift_source_target])
    # Check that the file was correctly mapped to the namespace parsed out of its file content.
    namespaces_by_files = result.context.products.get_data('_py_thrift_namespaces_by_files')
    self.assertEqual(
      [('org.pantsbuild.py_whatever', [
        (commented_thrift_source_target, 'src/py-thrift/with-header.thrift'),
      ])],
      list(namespaces_by_files.items()))
