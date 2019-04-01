# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals


def sanitize_crate_name(create_name):
  return create_name.replace('-', '_')


def reduce_invocation(invocation):
  invocation.pop('kind', None)
  return invocation
