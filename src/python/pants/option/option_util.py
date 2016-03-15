# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.option.custom_types import list_option


def is_boolean_option(kwargs):
  return kwargs.get('action') in ('store_false', 'store_true')


def is_list_option(kwargs):
  return kwargs.get('action') == 'append' or kwargs.get('type') == list_option
