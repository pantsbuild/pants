# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from itertools import chain


def get_default_converter():
  # https://github.com/rust-lang/cargo/blob/dc83ead224d8622f748f507574e1448a28d8dcc7/src/cargo/core/compiler/custom_build.rs#L482
  return {
      'rustc-link-lib': lambda kind: ['-l', kind],
      'rustc-link-search': lambda path: ['-L', path],
      'rustc-flags': lambda flags: spilt_flags(flags),
      'rustc-cfg': lambda cfg: ['--cfg', cfg],
      'rustc-env': lambda var_value: spilt_into_key_value(var_value),
      'warning': lambda warning: warning,
      'rerun-if-changed': lambda file: file,
      'rerun-if-env-changed': lambda env: env,
  }


def spilt_flags(flags):
  array_flags = flags.split(' ')
  filter_whitespaces = list(filter(lambda flag: flag.strip() != '', array_flags))
  iter_flags = iter(filter_whitespaces)
  return list(chain.from_iterable(map(list, zip(iter_flags, iter_flags))))


def spilt_into_key_value(key_value_str):
  key_value = key_value_str.split('=', 1)
  return key_value


def convert(key, value, converter):
  convert_fn = converter.get(key, None)
  if convert_fn:
    return [key, convert_fn(value)]
  else:
    return [key, value]


def parse_cargo_statement(cargo_statement):
  converter = get_default_converter()
  key_value = spilt_into_key_value(cargo_statement)
  if len(key_value) == 2:
    key, value = key_value
    return convert(key, value, converter)
  else:
    return key_value


def parse_multiple_cargo_statements(cargo_statements):
  result = {
      'rustc-link-lib': [],
      'rustc-link-search': [],
      'rustc-flags': [],
      'rustc-cfg': [],
      'rustc-env': [],
      'warning': [],
      'rerun-if-changed': [],
      'rerun-if-env-changed': [],
  }

  cargo_statements_without_prefix = list(
      map(lambda cargo: cargo.split('cargo:', 1)[1], cargo_statements))

  for cargo_statement in cargo_statements_without_prefix:
    key_value = parse_cargo_statement(cargo_statement)
    if len(key_value) == 2:
      key = key_value[0]
      value = key_value[1]
      in_result = result.get(key, None)
      if in_result is not None:
        result[key].append(value)
      else:
        result['warning'].append('(Pants) Unsupported cargo statement: {0} - {1}'.format(
            key, value))
    else:
      result['warning'].append('(Pants) Unsupported cargo statement: {0}'.format(key_value))
  return result


def filter_cargo_statements(build_output):
  return list(filter(lambda line: line.startswith('cargo:', 0, 6), build_output))
