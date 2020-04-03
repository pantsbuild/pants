# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.targets.python_target import PythonTarget
from pants.util.collections import ensure_str_list


class PythonTests(PythonTarget):
    """Python tests.

    :API: public
    """

    # These are the patterns matched by pytest's test discovery, plus pytest's config hook file.
    default_sources_globs = ("test_*.py", "*_test.py", "conftest.py")

    @classmethod
    def alias(cls):
        return "python_tests"

    def __init__(self, coverage=None, timeout=None, **kwargs):
        """
        :param coverage: the module(s) whose coverage should be generated, e.g.
          'twitter.common.log' or ['twitter.common.log', 'twitter.common.http']
        :param int timeout: A timeout (in seconds) which covers the total runtime of all tests in this
          target. Only applied if `--test-pytest-timeouts` is set to True.
        """
        self._coverage = (
            ensure_str_list(coverage, allow_single_str=True) if coverage is not None else []
        )
        self._timeout = timeout
        super().__init__(**kwargs)

    @property
    def coverage(self):
        """
        :API: public
        """
        return self._coverage

    @property
    def timeout(self):
        """
        :API: public
        """
        return self._timeout
