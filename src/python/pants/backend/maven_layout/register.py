# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.maven_layout.maven_layout import maven_layout


def register_goals():
  pass


def register_commands():
  pass


def target_aliases():
  return {}


def object_aliases():
  return {}


def applicative_path_relative_util_aliases():
  return {}


def target_creation_utils():
  return {}


def partial_path_relative_util_aliases():
  return {
    'maven_layout': maven_layout,
  }
