# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import ast
import keyword
import re
from functools import wraps

import six

from pants.contrib.python.checks.checker.common import CheckstylePlugin

ALL_LOWER_CASE_RE = re.compile(r"^[a-z][a-z\d]*$")
ALL_UPPER_CASE_RE = re.compile(r"^[A-Z][A-Z\d]+$")
LOWER_SNAKE_RE = re.compile(r"^([a-z][a-z\d]*)(_[a-z\d]+)*$")
UPPER_SNAKE_RE = re.compile(r"^([A-Z][A-Z\d]*)(_[A-Z\d]+)*$")
UPPER_CAMEL_RE = re.compile(r"^([A-Z][a-z\d]*)+$")
RESERVED_NAMES = frozenset(keyword.kwlist)
BUILTIN_NAMES = dir(six.moves.builtins)


def allow_underscores(num):
    def wrap(function):
        @wraps(function)
        def wrapped_function(name):
            if name.startswith("_" * (num + 1)):
                return False
            return function(name.lstrip("_"))

        return wrapped_function

    return wrap


@allow_underscores(1)
def is_upper_camel(name):
    """UpperCamel, AllowingHTTPAbbreviations, _WithUpToOneUnderscoreAllowable."""
    return bool(UPPER_CAMEL_RE.match(name) and not ALL_UPPER_CASE_RE.match(name))


@allow_underscores(2)
def is_lower_snake(name):
    """lower_snake_case, _with, __two_underscores_allowable."""
    return LOWER_SNAKE_RE.match(name) is not None


def is_reserved_name(name):
    return name in BUILTIN_NAMES or name in RESERVED_NAMES


def is_reserved_with_trailing_underscore(name):
    """For example, super_, id_, type_"""
    if name.endswith("_") and not name.endswith("__"):
        return is_reserved_name(name[:-1])
    return False


def is_builtin_name(name):
    """For example, __foo__ or __bar__."""
    if name.startswith("__") and name.endswith("__"):
        return ALL_LOWER_CASE_RE.match(name[2:-2]) is not None
    return False


@allow_underscores(2)
def is_constant(name):
    return UPPER_SNAKE_RE.match(name) is not None


class PEP8VariableNames(CheckstylePlugin):
    """Enforces PEP8 recommendations for variable names.

    Specifically:
       UpperCamel class names
       lower_snake / _lower_snake / __lower_snake function names
       lower_snake expression variable names
       CLASS_LEVEL_CONSTANTS = {}
       GLOBAL_LEVEL_CONSTANTS = {}
    """

    @classmethod
    def name(cls):
        return "variable-names"

    CLASS_GLOBAL_BUILTINS = frozenset({"__slots__", "__metaclass__"})

    def iter_class_methods(self, class_node):
        for node in class_node.body:
            if isinstance(node, ast.FunctionDef):
                yield node

    def iter_class_globals(self, class_node):
        for node in class_node.body:
            # TODO(wickman) Occasionally you have the pattern where you set methods equal to each other
            # which should be allowable, for example:
            #   class Foo(object):
            #     def bar(self):
            #       pass
            #     alt_bar = bar
            if isinstance(node, ast.Assign):
                for name in node.targets:
                    if isinstance(name, ast.Name):
                        yield name

    def nits(self):
        class_methods = set()
        all_methods = {
            function_def
            for function_def in ast.walk(self.python_file.tree)
            if isinstance(function_def, ast.FunctionDef)
        }

        for class_def in self.iter_ast_types(ast.ClassDef):
            if not is_upper_camel(class_def.name):
                yield self.error("T000", "Classes must be UpperCamelCased", class_def)
            for class_global in self.iter_class_globals(class_def):
                if (
                    not is_constant(class_global.id)
                    and class_global.id not in self.CLASS_GLOBAL_BUILTINS
                ):
                    yield self.error(
                        "T001", "Class globals must be UPPER_SNAKE_CASED", class_global
                    )
            if not class_def.bases or all(
                isinstance(base, ast.Name) and base.id == "object" for base in class_def.bases
            ):
                class_methods.update(self.iter_class_methods(class_def))
            else:
                # If the class is inheriting from anything that is potentially a bad actor, rely
                # upon checking that bad actor out of band.  Fixes PANTS-172.
                for method in self.iter_class_methods(class_def):
                    all_methods.discard(method)

        for function_def in all_methods - class_methods:
            if is_reserved_name(function_def.name):
                yield self.error("T801", "Method name overrides a builtin.", function_def)

        # TODO(wickman) Only enforce this for classes that derive from object.  If they
        # don't derive object, it's possible that the superclass naming is out of its
        # control.
        for function_def in all_methods:
            if not any(
                (
                    is_lower_snake(function_def.name),
                    is_builtin_name(function_def.name),
                    is_reserved_with_trailing_underscore(function_def.name),
                )
            ):
                yield self.error("T002", "Method names must be lower_snake_cased", function_def)
