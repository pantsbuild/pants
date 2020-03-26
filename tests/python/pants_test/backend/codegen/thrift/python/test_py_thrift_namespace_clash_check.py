# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.backend.codegen.thrift.python.py_thrift_namespace_clash_check import (
    PyThriftNamespaceClashCheck,
)
from pants.backend.codegen.thrift.python.python_thrift_library import PythonThriftLibrary
from pants.testutil.task_test_base import DeclarativeTaskTestMixin, TaskTestBase
from pants.util.dirutil import read_file


class PyThriftNamespaceClashCheckTest(TaskTestBase, DeclarativeTaskTestMixin):
    @classmethod
    def task_type(cls):
        return PyThriftNamespaceClashCheck

    _target_specs = {
        "src/py-thrift:with-comments-and-other-namespaces": {
            "target_type": PythonThriftLibrary,
            "sources": ["with-header.thrift"],
            "filemap": {
                "with-header.thrift": """\
// Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

namespace java org.pantsbuild.whatever
namespace py org.pantsbuild.py_whatever

struct A {}
""",
            },
        },
        "src/py-thrift:no-py-namespace": {
            "target_type": PythonThriftLibrary,
            "sources": ["bad.thrift"],
            "filemap": {
                "bad.thrift": """\
#@namespace scala org.pantsbuild.whatever
namespace java org.pantsbuild.whatever

struct A {}
""",
            },
        },
        "src/py-thrift:clashing-namespace": {
            "target_type": PythonThriftLibrary,
            "sources": ["a.thrift", "b.thrift"],
            "filemap": {
                "a.thrift": """\
namespace py org.pantsbuild.namespace

struct A {}
""",
                "b.thrift": """\
namespace py org.pantsbuild.namespace

struct B {}
""",
            },
        },
        "src/py-thrift-clashing:clashingA": {
            "target_type": PythonThriftLibrary,
            "sources": ["a.thrift"],
            "filemap": {
                "a.thrift": """\
namespace py org.pantsbuild.namespace

struct A {}
""",
            },
        },
        "src/py-thrift-clashing:clashingB": {
            "target_type": PythonThriftLibrary,
            "sources": ["b.thrift"],
            "filemap": {
                "b.thrift": """\
namespace py org.pantsbuild.namespace

struct B {}
""",
            },
        },
    }

    def _target_dict(self):
        return self.populate_target_dict(self._target_specs)

    def _run_tasks(
        self, target_roots, strict_missing_py_namespace=False, strict_clashing_py_namespace=False
    ):
        self.set_options(
            strict_missing_py_namespace=strict_missing_py_namespace,
            strict_clashing_py_namespace=strict_clashing_py_namespace,
        )
        return self.invoke_tasks(target_roots=target_roots)

    _exception_prelude = """\
Clashing namespaces for python thrift library sources detected in build graph. This will silently
overwrite previously generated python sources with generated sources from thrift files declaring the
same python namespace. This is an upstream WONTFIX in thrift, see:
      https://issues.apache.org/jira/browse/THRIFT-515
Errors:"""

    def test_no_py_namespace(self):
        no_py_namespace_target = self._target_dict()["no-py-namespace"]
        with self.assertRaises(PyThriftNamespaceClashCheck.NamespaceExtractionError) as cm:
            self._run_tasks(target_roots=[no_py_namespace_target], strict_missing_py_namespace=True)
        self.assertEqual(
            str(cm.exception),
            """\
Python namespaces could not be extracted from some thrift sources. Declaring a `namespace py` in
thrift sources for python thrift library targets will soon become required.

1 python library target(s) contained thrift sources not declaring a python namespace. The targets
and/or files which need to be edited will be dumped to: {}
""".format(
                cm.exception.output_file
            ),
        )
        self.assertEqual(
            "src/py-thrift:no-py-namespace: [src/py-thrift/bad.thrift]\n",
            read_file(cm.exception.output_file),
        )

    def test_clashing_namespace_same_target(self):
        clashing_same_target = self._target_dict()["clashing-namespace"]
        with self.assertRaisesWithMessage(
            PyThriftNamespaceClashCheck.ClashingNamespaceError,
            """{}
org.pantsbuild.namespace: [(src/py-thrift:clashing-namespace, src/py-thrift/a.thrift), (src/py-thrift:clashing-namespace, src/py-thrift/b.thrift)]
""".format(
                self._exception_prelude
            ),
        ):
            self._run_tasks(target_roots=[clashing_same_target], strict_clashing_py_namespace=True)
        self._run_tasks(target_roots=[clashing_same_target], strict_clashing_py_namespace=False)

    def test_clashing_namespace_multiple_targets(self):
        target_dict = self._target_dict()
        clashing_targets = [target_dict[k] for k in ["clashingA", "clashingB"]]
        with self.assertRaisesWithMessage(
            PyThriftNamespaceClashCheck.ClashingNamespaceError,
            """{}
org.pantsbuild.namespace: [(src/py-thrift-clashing:clashingA, src/py-thrift-clashing/a.thrift), (src/py-thrift-clashing:clashingB, src/py-thrift-clashing/b.thrift)]
""".format(
                self._exception_prelude
            ),
        ):
            self._run_tasks(target_roots=clashing_targets, strict_clashing_py_namespace=True)
        self._run_tasks(target_roots=clashing_targets, strict_clashing_py_namespace=False)

    def test_accepts_py_namespace_with_comments_above(self):
        commented_thrift_source_target = self._target_dict()["with-comments-and-other-namespaces"]
        result = self._run_tasks(
            target_roots=[commented_thrift_source_target],
            strict_missing_py_namespace=True,
            strict_clashing_py_namespace=True,
        )
        # Check that the file was correctly mapped to the namespace parsed out of its file content.
        namespaces_by_files = result.context.products.get_data("_py_thrift_namespaces_by_files")
        self.assertEqual(
            [
                (
                    "org.pantsbuild.py_whatever",
                    [(commented_thrift_source_target, "src/py-thrift/with-header.thrift")],
                )
            ],
            list(namespaces_by_files.items()),
        )
