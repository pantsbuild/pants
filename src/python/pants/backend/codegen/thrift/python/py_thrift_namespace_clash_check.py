# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re
from collections import OrderedDict, defaultdict

from pants.backend.codegen.thrift.python.python_thrift_library import PythonThriftLibrary
from pants.base.exceptions import TaskError
from pants.engine.fs import FilesContent
from pants.task.task import Task
from pants.util.dirutil import safe_file_dump


class PyThriftNamespaceClashCheck(Task):
    """Check that no python thrift libraries in the build graph have files with clashing namespaces.

    This is a temporary workaround for https://issues.apache.org/jira/browse/THRIFT-515. A real fix
    would ideally be to extend Scrooge to support clashing namespaces with Python code. A second-
    best solution would be to check all *thrift* libraries in the build graph, but there is
    currently no "ThriftLibraryMixin" or other way to identify targets containing thrift code
    generically.
    """

    # This scope is set for testing only.
    options_scope = "py-thrift-namespace-clash-check"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--strict-clashing-py-namespace",
            type=bool,
            default=False,
            fingerprint=True,
            help="Whether to fail the build if thrift sources have clashing py namespaces.",
        )
        register(
            "--strict-missing-py-namespace",
            type=bool,
            default=False,
            fingerprint=True,
            help="Whether to fail the build if thrift sources is missing py namespaces.",
        )

    @classmethod
    def product_types(cls):
        """Populate a dict mapping thrift sources to their namespaces and owning targets for
        testing."""
        return ["_py_thrift_namespaces_by_files"]

    def _get_python_thrift_library_sources(self, py_thrift_targets):
        """Get file contents for python thrift library targets."""
        target_snapshots = OrderedDict(
            (t, t.sources_snapshot(scheduler=self.context._scheduler).directory_digest)
            for t in py_thrift_targets
        )
        filescontent_by_target = OrderedDict(
            zip(
                target_snapshots.keys(),
                self.context._scheduler.product_request(FilesContent, target_snapshots.values()),
            )
        )
        thrift_file_sources_by_target = OrderedDict(
            (
                t,
                [
                    (file_content.path, file_content.content)
                    for file_content in all_content.dependencies
                ],
            )
            for t, all_content in filescontent_by_target.items()
        )
        return thrift_file_sources_by_target

    _py_namespace_pattern = re.compile(r"^namespace\s+py\s+([^\s]+)$", flags=re.MULTILINE)

    class NamespaceParseFailure(Exception):
        pass

    def _extract_py_namespace_from_content(self, target, thrift_filename, thrift_source_content):
        py_namespace_match = self._py_namespace_pattern.search(thrift_source_content)
        if py_namespace_match is None:
            raise self.NamespaceParseFailure()
        return py_namespace_match.group(1)

    class NamespaceExtractionError(TaskError):
        def __init__(self, output_file, msg):
            self.output_file = output_file
            super(PyThriftNamespaceClashCheck.NamespaceExtractionError, self).__init__(msg)

    def _extract_all_python_namespaces(self, thrift_file_sources_by_target, is_strict):
        """Extract the python namespace from each thrift source file."""
        py_namespaces_by_target = OrderedDict()
        failing_py_thrift_by_target = defaultdict(list)
        for t, all_content in thrift_file_sources_by_target.items():
            py_namespaces_by_target[t] = []
            for (path, content) in all_content:
                try:
                    py_namespaces_by_target[t].append(
                        # File content is provided as a binary string, so we have to decode it.
                        (path, self._extract_py_namespace_from_content(t, path, content.decode()))
                    )
                except self.NamespaceParseFailure:
                    failing_py_thrift_by_target[t].append(path)

        if failing_py_thrift_by_target:
            # We dump the output to a file here because the output can be very long in some repos.
            no_py_namespace_output_file = os.path.join(
                self.workdir, "no-python-namespace-output.txt"
            )

            pretty_printed_failures = "\n".join(
                "{}: [{}]".format(t.address.spec, ", ".join(paths))
                for t, paths in failing_py_thrift_by_target.items()
            )
            error = self.NamespaceExtractionError(
                no_py_namespace_output_file,
                """\
Python namespaces could not be extracted from some thrift sources. Declaring a `namespace py` in
thrift sources for python thrift library targets will soon become required.

{} python library target(s) contained thrift sources not declaring a python namespace. The targets
and/or files which need to be edited will be dumped to: {}
""".format(
                    len(failing_py_thrift_by_target), no_py_namespace_output_file
                ),
            )

            safe_file_dump(no_py_namespace_output_file, "{}\n".format(pretty_printed_failures))

            if is_strict:
                raise error
            else:
                self.context.log.warn(str(error))
        return py_namespaces_by_target

    class ClashingNamespaceError(TaskError):
        pass

    def _determine_clashing_namespaces(self, py_namespaces_by_target, is_strict):
        """Check for any overlapping namespaces."""
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
            pretty_printed_clashing = "\n".join(
                "{}: [{}]".format(
                    namespace,
                    ", ".join("({}, {})".format(t.address.spec, path) for (t, path) in all_paths),
                )
                for namespace, all_paths in clashing_namespaces.items()
            )
            error = self.ClashingNamespaceError(
                """\
Clashing namespaces for python thrift library sources detected in build graph. This will silently
overwrite previously generated python sources with generated sources from thrift files declaring the
same python namespace. This is an upstream WONTFIX in thrift, see:
      https://issues.apache.org/jira/browse/THRIFT-515
Errors:
{}
""".format(
                    pretty_printed_clashing
                )
            )
            if is_strict:
                raise error
            else:
                self.context.log.warn(str(error))
        return namespaces_by_files

    def execute(self):
        py_thrift_targets = self.get_targets(lambda tgt: isinstance(tgt, PythonThriftLibrary))
        thrift_file_sources_by_target = self._get_python_thrift_library_sources(py_thrift_targets)
        py_namespaces_by_target = self._extract_all_python_namespaces(
            thrift_file_sources_by_target, self.get_options().strict_missing_py_namespace
        )
        namespaces_by_files = self._determine_clashing_namespaces(
            py_namespaces_by_target, self.get_options().strict_clashing_py_namespace
        )
        self.context.products.register_data("_py_thrift_namespaces_by_files", namespaces_by_files)
