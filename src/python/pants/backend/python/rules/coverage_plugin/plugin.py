# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os

from coverage import CoveragePlugin, FileTracer
from coverage.config import DEFAULT_PARTIAL, DEFAULT_PARTIAL_ALWAYS
from coverage.misc import join_regex
from coverage.parser import PythonParser
from coverage.python import PythonFileReporter


class PantsFileTracer(FileTracer):
    """This tells Coverage which files Pants 'owns'."""

    def __init__(self, filename):
        super(PantsFileTracer, self).__init__()
        self.filename = filename

    def source_filename(self):
        return self.filename


class PantsPythonFileReporter(PythonFileReporter):
    def __init__(self, stripped_filename, unstripped_filename):
        super(PantsPythonFileReporter, self).__init__(morf=stripped_filename)
        self.unstripped_filename = unstripped_filename

    # This is what gets used in reports.
    def relative_filename(self):
        return self.unstripped_filename

    # We override to work around https://github.com/nedbat/coveragepy/issues/646.
    @property
    def parser(self):
        if self._parser is None:
            self._parser = PythonParser(filename=self.filename)
            self._parser.parse_source()
        return self._parser

    # We override to work around https://github.com/nedbat/coveragepy/issues/646.
    def no_branch_lines(self):
        return self.parser.lines_matching(
            join_regex(DEFAULT_PARTIAL[:]), join_regex(DEFAULT_PARTIAL_ALWAYS[:])
        )


class SourceRootRemappingPlugin(CoveragePlugin):
    """A plugin that knows how to restore source roots from stripped files in Coverage reports.

    Both `file_tracer` and `find_executable_files` teach Coverage which files are "owned" by this
    plugin, meaning which files should have their filenames be changed in the final report.

    `file_reporter` hooks up our custom logic to add back the source root in the final report.
    """

    def __init__(self, chroot_path, stripped_files_to_source_roots):
        super(SourceRootRemappingPlugin, self).__init__()
        self.chroot_path = chroot_path
        self.stripped_files_to_source_roots = stripped_files_to_source_roots

    def file_tracer(self, filename):
        if not filename.startswith(self.chroot_path):
            return None
        stripped_file = os.path.relpath(filename, self.chroot_path)
        if stripped_file in self.stripped_files_to_source_roots:
            return PantsFileTracer(filename)

    def find_executable_files(self, src_dir):
        if not src_dir.startswith(self.chroot_path):
            return None
        for dirname, _, filenames in os.walk(src_dir):
            relative_dirname = os.path.relpath(dirname, self.chroot_path)
            for filename in filenames:
                stripped_file = os.path.join(relative_dirname, filename)
                if stripped_file in self.stripped_files_to_source_roots:
                    yield os.path.join(dirname, filename)

    def file_reporter(self, filename):
        stripped_file = os.path.relpath(filename, self.chroot_path)
        source_root = self.stripped_files_to_source_roots[stripped_file]
        return PantsPythonFileReporter(
            stripped_filename=stripped_file,
            unstripped_filename=os.path.join(source_root, stripped_file),
        )


def coverage_init(reg, options):
    chroot_path = os.getcwd()
    stripped_files_to_source_roots = json.loads(options["stripped_files_to_source_roots"])
    reg.add_file_tracer(SourceRootRemappingPlugin(chroot_path, stripped_files_to_source_roots))
