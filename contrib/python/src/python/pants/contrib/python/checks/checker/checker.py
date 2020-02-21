# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import argparse
import functools
import json
import logging
import re
import sys

from pants.contrib.python.checks.checker.class_factoring import ClassFactoring
from pants.contrib.python.checks.checker.common import CheckSyntaxError, Nit, PythonFile
from pants.contrib.python.checks.checker.constant_logic import ConstantLogic
from pants.contrib.python.checks.checker.except_statements import ExceptStatements
from pants.contrib.python.checks.checker.file_excluder import FileExcluder
from pants.contrib.python.checks.checker.future_compatibility import FutureCompatibility
from pants.contrib.python.checks.checker.import_order import ImportOrder
from pants.contrib.python.checks.checker.indentation import Indentation
from pants.contrib.python.checks.checker.missing_contextmanager import MissingContextManager
from pants.contrib.python.checks.checker.new_style_classes import NewStyleClasses
from pants.contrib.python.checks.checker.newlines import Newlines
from pants.contrib.python.checks.checker.print_statements import PrintStatements
from pants.contrib.python.checks.checker.pycodestyle import PyCodeStyleChecker
from pants.contrib.python.checks.checker.pyflakes import PyflakesChecker
from pants.contrib.python.checks.checker.trailing_whitespace import TrailingWhitespace
from pants.contrib.python.checks.checker.variable_names import PEP8VariableNames

_NOQA_LINE_SEARCH = re.compile(r"# noqa\b").search
_NOQA_FILE_SEARCH = re.compile(r"# (flake8|checkstyle): noqa$").search


def line_contains_noqa(line):
    return _NOQA_LINE_SEARCH(line) is not None


def noqa_file_filter(python_file):
    return any(_NOQA_FILE_SEARCH(line) is not None for line in python_file.lines)


class Checker(object):
    log = logging.getLogger(__name__)

    def __init__(self, root_dir, severity, strict, suppress, plugin_factories):
        self._root_dir = root_dir
        self._severity = severity
        self._strict = strict
        self._excluder = FileExcluder(suppress, self.log) if suppress else None
        self._plugin_factories = plugin_factories

    def _get_nits(self, filename):
        """Iterate over the instances style checker and yield Nits.

        :param filename: str pointing to a file within the buildroot.
        """
        try:
            python_file = PythonFile.parse(filename, root=self._root_dir)
        except CheckSyntaxError as e:
            yield e.as_nit()
            return

        if noqa_file_filter(python_file):
            return

        if self._excluder:
            # Filter out any suppressed plugins
            check_plugins = [
                (plugin_name, plugin_factory)
                for plugin_name, plugin_factory in self._plugin_factories.items()
                if self._excluder.should_include(filename, plugin_name)
            ]
        else:
            check_plugins = self._plugin_factories.items()

        for plugin_name, plugin_factory in check_plugins:
            for i, nit in enumerate(plugin_factory(python_file)):
                if i == 0:
                    # NB: Add debug log header for nits from each plugin, but only if there are nits from it.
                    self.log.debug("Nits from plugin {} for {}".format(plugin_name, filename))

                if not nit.has_lines_to_display:
                    yield nit
                    continue

                if all(not line_contains_noqa(line) for line in nit.lines):
                    yield nit

    def _check_file(self, filename):
        """Process python file looking for indications of problems.

        :param filename: (str) Python source filename
        :return: (int) number of failures
        """
        # If the user specifies an invalid severity use comment.
        log_threshold = Nit.SEVERITY.get(self._severity, Nit.COMMENT)

        failure_count = 0
        fail_threshold = Nit.WARNING if self._strict else Nit.ERROR

        for i, nit in enumerate(self._get_nits(filename)):
            if i == 0:
                print()  # Add an extra newline to clean up the output only if we have nits.
            if nit.severity >= log_threshold:
                print("{nit}\n".format(nit=nit))
            if nit.severity >= fail_threshold:
                failure_count += 1
        return failure_count

    def checkstyle(self, sources):
        """Iterate over sources and run checker on each file.

        Files can be suppressed with a --suppress option which takes an xml file containing
        file paths that have exceptions and the plugins they need to ignore.

        :param sources: iterable containing source file names.
        :return: (int) number of failures
        """
        failure_count = 0
        for filename in sources:
            failure_count += self._check_file(filename)
        return failure_count


def plugins():
    """Returns a tuple of the plugin classes registered with the python style checker.

    :rtype: tuple of :class:`pants.contrib.python.checks.checker.common.CheckstylePlugin` subtypes
    """
    return (
        ClassFactoring,
        ConstantLogic,
        ExceptStatements,
        FutureCompatibility,
        ImportOrder,
        Indentation,
        MissingContextManager,
        NewStyleClasses,
        Newlines,
        PrintStatements,
        TrailingWhitespace,
        PEP8VariableNames,
        PyflakesChecker,
        PyCodeStyleChecker,
    )


def main(args=None):
    parser = argparse.ArgumentParser(
        description="A Python source code linter.", fromfile_prefix_chars="@"
    )
    parser.add_argument(
        "--root-dir",
        required=True,
        metavar="PATH",
        help="The absolute path to the root directory all sources passed are " "relative to",
    )
    parser.add_argument("sources", nargs="+")
    parser.add_argument(
        "--severity",
        type=str,
        default=Nit.SEVERITY[Nit.COMMENT],
        choices=[name for _, name in sorted(Nit.SEVERITY.items(), key=lambda item: item[0])],
        help="Only messages at this severity or higher are logged.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="If enabled, exit status will be non-zero for any nit at WARNING or " "higher.",
    )
    parser.add_argument(
        "--suppress",
        metavar="PATH",
        type=str,
        default=None,
        help="Takes a text file where specific rules on specific files will be " "skipped.",
    )

    for plugin_type in plugins():
        parser.add_argument(
            "--{}-options".format(plugin_type.name()),
            metavar="JSON",
            help="JSON formatted options for the {} plugin".format(plugin_type.name()),
        )

    args = parser.parse_args(args=args)

    plugin_factories = {}
    for plugin_type in plugins():
        option_name = "{}_options".format(plugin_type.name().replace("-", "_"))
        option_blob = getattr(args, option_name)
        option_dict = json.loads(option_blob) if option_blob else {}
        options = argparse.Namespace(**option_dict)
        if not options.skip:
            plugin_factories[plugin_type.name()] = functools.partial(plugin_type, options)

    checker = Checker(
        root_dir=args.root_dir,
        severity=args.severity,
        strict=args.strict,
        suppress=args.suppress,
        plugin_factories=plugin_factories,
    )
    failure_count = checker.checkstyle(args.sources)
    sys.exit(failure_count)
