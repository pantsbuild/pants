# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import zipfile
from contextlib import contextmanager

from pants.util.contextutil import open_zip


class CompileContext:
    """A context for the compilation of a target.

    This can be used to differentiate between a partially completed compile in a temporary location
    and a finalized compile in its permanent location.
    """

    def __init__(
        self,
        target,
        analysis_file,
        classes_dir,
        jar_file,
        log_dir,
        args_file,
        post_compile_merge_dir,
        sources,
        diagnostics_out,
    ):
        self.target = target
        self.analysis_file = analysis_file
        self.classes_dir = classes_dir
        self.jar_file = jar_file
        self.log_dir = log_dir
        self.args_file = args_file
        self.post_compile_merge_dir = post_compile_merge_dir
        self.sources = sources
        self.diagnostics_out = diagnostics_out

    @contextmanager
    def open_jar(self, mode):
        with open_zip(self.jar_file.path, mode=mode, compression=zipfile.ZIP_STORED) as jar:
            yield jar

    @property
    def _id(self):
        return (self.target, self.analysis_file, self.classes_dir.path, self.diagnostics_out)

    def __eq__(self, other):
        return self._id == other._id

    def __ne__(self, other):
        return self._id != other._id

    def __hash__(self):
        return hash(self._id)
