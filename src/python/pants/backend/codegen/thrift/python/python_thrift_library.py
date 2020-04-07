# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.targets.python_target import PythonTarget


class PythonThriftLibrary(PythonTarget):
    """A Python library generated from Thrift IDL files.

    :API: public
    """

    def __init__(self, **kwargs):
        """
        :param sources: thrift source files (If more than one tries to use the same
          namespace, beware https://issues.apache.org/jira/browse/THRIFT-515)
        :type sources: ``Fileset`` or list of strings. Paths are relative to the
          BUILD file's directory.
        """

        super().__init__(**kwargs)
