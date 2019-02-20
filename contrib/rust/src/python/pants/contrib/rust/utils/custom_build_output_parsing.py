# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals


def get_default_converter():
  return {
    'rustc-link-lib': lambda kind: ['-l', kind],
    'rustc-link-search': lambda path: ['-L', path],
    'rustc-flags': lambda path: ['-L', path],
    'rustc-cfg': lambda cfg: ['--cfg', cfg],
    'rustc-env': lambda var_value: var_value,
  }


def spilt_into_key_value(cargo_statement):
  key_value = cargo_statement.split('=', 1)
  return key_value


def translate(key, value, converter):
  transform = converter.get(key, None)
  if transform:
    return [key, transform(value)]
  else:
    return [key, value]


def parse_cargo_statement(cargo_statement):
  converter = get_default_converter()
  key_value = spilt_into_key_value(cargo_statement)
  if len(key_value) == 2:
    key, value = key_value
    return translate(key, value, converter)
  else:
    return key_value


def parse_multiple_cargo_statements(cargo_statements):
  result = {
    'rustc-link-lib': [],
    'rustc-link-search': [],
    'rustc-flags': [],
    'rustc-cfg': [],
    'rustc-env': [],
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
        print('Warn: Unsupported cargo statement: {0}'.format(key))
    else:
      print('Warn: Unsupported cargo statement: {0}'.format(key_value))
  return result


def filter_cargo_statements(output):
  return list(filter(lambda line: line.startswith('cargo:', 0, 6), output))
