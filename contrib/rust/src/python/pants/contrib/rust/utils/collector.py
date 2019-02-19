# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals


def args(args, collector):
  def _c_flag_filter(key_value, collector):
    needs = dict({
      'extra-filename': True,
    })

    is_key_value = key_value.split('=')

    if len(is_key_value) == 2:
      key, value = is_key_value
      has = needs.get(key, None)

      if has:
        collector.update({key: value})

  needs = dict({
    '--crate-name': lambda name, collector: collector.update({'crate_name': name}),
    '-C': _c_flag_filter,
  })

  for index, arg in enumerate(args):
    filter = needs.get(arg, None)
    if filter:
      filter(args[index + 1], collector)


def get_default_information():
  return dict({
    'args': args,
    'package_name': lambda name, collector: collector.update({'package_name': name})
  })


def get_test_target_information():
  return dict({
    'env': env
  })


def env(invocation, collector):
  needs = dict({
    'CARGO_MANIFEST_DIR': lambda key, vaule, collector: collector.update({key: vaule})
  })

  for key, value in invocation.items():
    filter = needs.get(key, None)
    if filter:
      filter(key, value, collector)


def collect_information(invocation, requirements):
  collector = dict()

  for key in invocation:
    found = requirements.get(key, None)
    if found:
      found(invocation[key], collector)

  return collector
