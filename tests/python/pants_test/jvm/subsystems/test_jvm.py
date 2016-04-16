# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools

from pants.backend.jvm.subsystems.jvm import JVM
from pants_test.subsystem.subsystem_util import create_subsystem


create_JVM = functools.partial(create_subsystem, JVM)


def test_options_default():
  jvm = create_JVM()
  assert jvm.options_default == jvm.get_jvm_options()


def test_options_simple():
  jvm = create_JVM(options=['-ea'])
  assert ['-ea'] == jvm.get_jvm_options()


def test_options_single_complex():
  jvm = create_JVM(options=['-ea "-cp mono.jar" -server'])
  assert ['-ea', '-cp mono.jar', '-server'] == jvm.get_jvm_options()


def test_options_multiple():
  jvm = create_JVM(options=['-ea', '"-cp mono.jar"', '-server'])
  assert ['-ea', '-cp mono.jar', '-server'] == jvm.get_jvm_options()


def test_explicit_debug():
  jvm = create_JVM(debug=True)
  assert '-Xdebug' in jvm.get_jvm_options()


def test_explicit_debug_with_options():
  jvm = create_JVM(options=['-ea'], debug=True)
  assert '-ea' in jvm.get_jvm_options()
  assert '-Xdebug' in jvm.get_jvm_options()


def test_implicit_via_debug_port():
  jvm = create_JVM(debug_port=1137)
  jvm_options = jvm.get_jvm_options()

  assert '-Xdebug' in jvm_options

  jdwp_options = None
  for option in jvm_options:
    if option.startswith('-Xrunjdwp:'):
      jdwp_options = dict(kv.split('=', 1) for kv in option.replace('-Xrunjdwp:', '').split(','))
      assert 'address' in jdwp_options
      assert '1137' in jdwp_options['address']
  assert jdwp_options is not None, 'Expected jdwp options to be present specifying the debug port.'


def test_explicit_debug_args():
  jvm = create_JVM(debug_args=['fred'])
  assert jvm.options_default + ['fred'] == jvm.get_jvm_options()


def test_explicit_debug_args_with_options():
  jvm = create_JVM(options=['-ea'], debug_args=['fred'])
  assert sorted(['-ea', 'fred']) == sorted(jvm.get_jvm_options())


def test_args_default():
  jvm = create_JVM()
  assert [] == jvm.get_program_args()


def test_args_single_simple():
  jvm = create_JVM(program_args=['a'])
  assert ['a'] == jvm.get_program_args()


def test_args_single_complex():
  jvm = create_JVM(program_args=['a "b c" d'])
  assert ['a', 'b c', 'd'] == jvm.get_program_args()


def test_args_multiple():
  jvm = create_JVM(program_args=['a', '"b c"', 'd'])
  assert ['a', 'b c', 'd'] == jvm.get_program_args()
