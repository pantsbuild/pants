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
  
  # scalac errors with strict_deps enabled. Some errors may still be missing.
  # below matches some of the common issues caused by missing exports.
  (r'\s*\[error\] [^:]+\.scala:\d+:\d+: Symbol \'\S+ \<none\>\.(?P<classname>\S+)\' is missing from the '
   r'classpath\.\n\s*\[error\] This symbol is required by \'(?P<type>\S+) (?P<dependee_classname>\S+)\'\.\n'
   r'\s*\[error\] Make sure that \S+ (?P<classnameonly>\S+) is in your classpath and check for conflicting '
   r'dependencies with `-Ylog-classpath`\.\n\s*\[error\] A full rebuild may help if '
   r'\'(?P<dependee_classnameonly>\S+)\.class\' was compiled against an incompatible version of '
   r'\<none\>\.(?P<packagename>\S+)\.'),
  (r'\s*\[error\] [^:]+\.scala:\d+:\d+: Symbol \'\S+ (?P<classname>\S+)\' is missing from the classpath\.\n\s*'
   r'\[error\] This symbol is required by \'(?P<type>\S+) (?P<dependee_classname>\S+)\'\.\n\s*'
   r'\[error\] Make sure that \S+ (?P<classnameonly>\S+) is in your classpath and check for conflicting dependencies '
   r'with `-Ylog-classpath`\.\n\s*\[error\] A full rebuild may help if \'(?P<dependee_classnameonly>\S+)\.class\' '
   r'was compiled against an incompatible version of (?P<packagename>\S+)\.'),
  # covers member types of traits not used in the extending type.
  (r'\s*\[error\] Symbol \'\S+ (?P<classname>\S+)\' is missing from the classpath\.\n\s*\[error\] This symbol is '
   r'required by \'method (?P<dependee_classname>\S+)\.(?P<method_name>[^\.]+)\'\.\n\s*\[error\] Make sure that \S+ '
   r'(?P<classnameonly>\S+) is in your classpath and check for conflicting dependencies with `-Ylog-classpath`\.\n\s*'
   r'\[error\] A full rebuild may help if \'(?P<dependee_classnameonly>\S+)\.class\' was compiled against an '
   r'incompatible version of (?P<packagename>\S+)\.'),

  # zinc errors.
  (r'\s*\[error\] ## Exception when compiling (?P<filename>\S+) and others\.\.\.\n'
   '\s*\[error\] Type (?P<classname>\S+) not present'),
  (r'\s*\[error\] ## Exception when compiling (?P<filename>\S+) and others\.\.\.\n'
   '\s*\[error\] java.lang.NoClassDefFoundError: (?P<classname>\S+)'),
]
