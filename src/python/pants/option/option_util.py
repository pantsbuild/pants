# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.option.custom_types import dict_with_files_option, list_option


def is_list_option(kwargs):
  return (kwargs.get('action') == 'append' or kwargs.get('type') == list or
          kwargs.get('type') == list_option)


def is_dict_option(kwargs):
  return kwargs.get('type') in (dict, dict_with_files_option)
