# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
import unittest
from textwrap import dedent

from pants.util.contextutil import stdio_as, temporary_dir
from pants.util.dirutil import safe_open

from pants.contrib.python.checks.checker import checker


class CheckstyleTest(unittest.TestCase):
    _MAX_LENGTH = 50

    def assert_checker(self, relpath, contents, expected_code=0, expected_message=""):
        with temporary_dir() as td:
            with safe_open(os.path.join(td, relpath), "w") as fp:
                fp.write(contents)

            args = ["--root-dir={}".format(td)]
            for plugin_type in checker.plugins():
                opts = {"skip": False, "max_length": self._MAX_LENGTH, "ignore": ["E111"]}
                args.append("--{}-options={}".format(plugin_type.name(), json.dumps(opts)))
            args.append(relpath)

            with open(os.path.join(td, "stdout"), "w+") as stdout:
                with open(os.path.join(td, "stderr"), "w+") as stderr:
                    with stdio_as(
                        stdout_fd=stdout.fileno(), stderr_fd=stderr.fileno(), stdin_fd=-1
                    ):
                        with self.assertRaises(SystemExit) as error:
                            checker.main(args=args)

                    def read_stdio(fp):
                        fp.flush()
                        fp.seek(0)
                        return fp.read()

                    self.assertEqual(
                        expected_code,
                        error.exception.code,
                        "STDOUT:\n{}\nSTDERR:\n{}".format(read_stdio(stdout), read_stdio(stderr)),
                    )

                    self.assertEqual(expected_message, read_stdio(stdout).strip())
                    self.assertEqual("", read_stdio(stderr))

    def test_failure_print_nit(self):
        contents = dedent(
            """
      class lower_case(object):
        pass
    """
        )

        msg = (
            """T000:ERROR   a/python/fail.py:002 Classes must be UpperCamelCased\n"""
            """     |class lower_case(object):"""
        )

        self.assert_checker(
            relpath="a/python/fail.py", contents=contents, expected_code=1, expected_message=msg
        )

    def test_syntax_error_nit(self):
        contents = dedent(
            """
      invalid python
    """
        )

        msg = (
            """E901:ERROR   a/python/error.py:002 SyntaxError: invalid syntax\n"""
            """     |\n"""
            """     |invalid python\n"""
            """     |"""
        )

        self.assert_checker(
            relpath="a/python/error.py", contents=contents, expected_code=1, expected_message=msg
        )

    def test_noqa_line(self):
        def content(noqa):
            return dedent(
                """
        SHORT_ENOUGH = True
        TOO_LONG = '{too_long}'{noqa}
      """.format(
                    too_long="a" * self._MAX_LENGTH, noqa="  # noqa" if noqa else ""
                )
            )

        self.assert_checker(relpath="a/python/pass.py", contents=content(noqa=True))

        msg = (
            """E501:ERROR   PythonFile(a/python/fail.py):003 line too long (63 > 50 characters)\n"""
            """     |TOO_LONG = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'"""
        )

        self.assert_checker(
            relpath="a/python/fail.py",
            contents=content(noqa=False),
            expected_code=1,
            expected_message=msg,
        )

    def test_noqa_file(self):
        def content(noqa):
            return dedent(
                """
        {noqa}
        SHORT_ENOUGH = True
        TOO_LONG = '{too_long}'
      """.format(
                    noqa="# checkstyle: noqa" if noqa else "", too_long="a" * self._MAX_LENGTH
                )
            )

        self.assert_checker(relpath="a/python/pass.py", contents=content(noqa=True))

        msg = (
            """E501:ERROR   PythonFile(a/python/fail.py):004 line too long (63 > 50 characters)\n"""
            """     |TOO_LONG = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'"""
        )

        self.assert_checker(
            relpath="a/python/fail.py",
            contents=content(noqa=False),
            expected_code=1,
            expected_message=msg,
        )
