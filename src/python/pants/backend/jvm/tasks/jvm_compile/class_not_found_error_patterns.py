# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


CLASS_NOT_FOUND_ERROR_PATTERNS = [
  # javac errors.
  (r'\s*\[error\] (?P<filename>\S+):(?P<lineno>\d+):(\d+): cannot find symbol\n'
   '\s*\[error\]   symbol:   class (\S+)\n'
   '\s*\[error\]   location: package (\S+)\n'
   '\s*\[error\] import (?P<classname>\S+);'),
  (r'\s*\[error\] (?P<filename>\S+):(?P<lineno>\d+):(\d+): cannot access (\S+)\n'
   '\s*\[error\]   class file for (?P<classname>\S+) not found'),
  (r'\s*\[error\] (?P<filename>\S+):(?P<lineno>\d+):(\d+): package (\S+) does not exist\n'
   '\s*\[error\] import (?P<classname>\S+);'),
  (r'\s*\[error\] (?P<filename>\S+):(?P<lineno>\d+):(\d+): cannot find symbol\n'
   '\s*\[error\]   symbol:   class (?P<classnameonly>\S+)\n'
   '\s*\[error\]   location: package (?P<packagename>\S+)'),
  (r'\s*\[error\] (?P<filename>\S+):(?P<lineno>\d+):(\d+): '
   'package (?P<packagename>\S+) does not exist\n'
   '\s*\[error\] .*\W(?P<classname>(?P=packagename)\.\w+)\W.*'),
  (r'.*java.lang.NoClassDefFoundError: (?P<classname>\S+)'),

  # scalac errors. More work undergoing to improve scalac error messages.
  (r'\s*\[error\] missing or invalid dependency detected while loading class file '
   '\'(?P<dependee_classname>\S+)\.class\'\.\n'
   '\s*\[error\] Could not access type (?P<classnameonly>\S+) in (value|package) '
   '(?P<packagename>\S+),'),
  (r'\s*\[error\] (?P<filename>\S+):(?P<lineno>\d+):(\d+): exception during macro expansion:\s*\n'
   '\s*\[error\] java.lang.ClassNotFoundException: (?P<classname>\S+)'),
  (r'\s*\[error\] (?P<filename>\S+):(?P<lineno>\d+):(\d+): object (\S+) '
   'is not a member of package (\S+)\n'
   '\s*\[error\] import (?P<classname>\S+)'),
  (r'\s*\[error\] Class (?P<classname>\S+) not found \- continuing with a stub\.'),

  # zinc errors.
  (r'\s*\[error\] ## Exception when compiling (?P<filename>\S+) and others\.\.\.\n'
   '\s*\[error\] Type (?P<classname>\S+) not present'),
  (r'\s*\[error\] ## Exception when compiling (?P<filename>\S+) and others\.\.\.\n'
   '\s*\[error\] java.lang.NoClassDefFoundError: (?P<classname>\S+)'),
]
