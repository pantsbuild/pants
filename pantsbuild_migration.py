# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
import sys


PANTS_ROOT = os.path.dirname(os.path.realpath(__file__))
SRC_ROOT = os.path.join(PANTS_ROOT, 'src', 'python')
TESTS_ROOT = os.path.join(PANTS_ROOT, 'tests', 'python')


KNOWN_STD_LIBS = set(["abc", "anydbm", "argparse", "array", "asynchat", "asyncore", "atexit", "base64",
                      "BaseHTTPServer", "bisect", "bz2", "calendar", "cgitb", "cmd", "codecs",
                      "collections", "commands", "compileall", "ConfigParser", "contextlib", "Cookie",
                      "copy", "cPickle", "cProfile", "cStringIO", "csv", "datetime", "dbhash", "dbm",
                      "decimal", "difflib", "dircache", "dis", "doctest", "dumbdbm", "EasyDialogs",
                      "errno", "exceptions", "filecmp", "fileinput", "fnmatch", "fractions",
                      "functools", "gc", "gdbm", "getopt", "getpass", "gettext", "glob", "grp", "gzip",
                      "hashlib", "heapq", "hmac", "imaplib", "imp", "inspect", "itertools", "json",
                      "linecache", "locale", "logging", "mailbox", "math", "mhlib", "mmap",
                      "multiprocessing", "operator", "optparse", "os", "pdb", "pickle", "pipes",
                      "pkgutil", "platform", "plistlib", "pprint", "profile", "pstats", "pwd", "pyclbr",
                      "pydoc", "Queue", "random", "re", "readline", "resource", "rlcompleter",
                      "robotparser", "sched", "select", "shelve", "shlex", "shutil", "signal",
                      "SimpleXMLRPCServer", "site", "sitecustomize", "smtpd", "smtplib", "socket",
                      "SocketServer", "sqlite3", "string", "StringIO", "struct", "subprocess", "sys",
                      "sysconfig", "tabnanny", "tarfile", "tempfile", "textwrap", "threading", "time",
                      "timeit", "trace", "traceback", "unittest", "urllib", "urllib2", "urlparse",
                      "usercustomize", "uuid", "warnings", "weakref", "webbrowser", "whichdb", "xml",
                      "xmlrpclib", "zipfile", "zipimport", "zlib", 'builtins', '__builtin__'])

OLD_PANTS_PACKAGE = 'twitter.pants'
NEW_PANTS_PACKAGE = 'pants'

IMPORT_RE = re.compile(r'import\s+(.*)')
FROM_IMPORT_RE = re.compile(r'from\s+(.*)\s+import\s+(.*)')

AUTHOR_RE = re.compile(r'__author__\s*=\s*.+')

def has_continuation(line):
  return line.endswith('\\')

HEADER_COMMENT = [
  '# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).',
  '# Licensed under the Apache License, Version 2.0 (see LICENSE).'
]

FUTURE_IMPORTS = [
  'from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,',
  '                        print_function, unicode_literals)'
]

class Import(object):
  def __init__(self, symbol):
    self._symbol = symbol.strip()
    if self._symbol.startswith(OLD_PANTS_PACKAGE):
      self._symbol = self._symbol[8:]

  def package(self):
    return self._symbol

  def sort_key(self):
    return 'AAA' + self._symbol

  def __str__(self):
    return 'import %s' % self._symbol


class FromImport(object):
  def __init__(self, frm, symbols):
    self._from = frm.strip()
    if self._from.startswith(OLD_PANTS_PACKAGE):
      self._from = NEW_PANTS_PACKAGE + self._from[len(OLD_PANTS_PACKAGE):]
    self._symbols = filter(None, [filter(lambda c: c not in '()', s.strip()).strip() for s in symbols])

  def package(self):
    return self._from

  def sort_key(self):
    return 'ZZZ' + self._from

  def __str__(self):
    return 'from %s import %s' % (self._from, ', '.join(sorted(self._symbols)))


class BuildFile(object):
  def __init__(self, path):
    self._path = path
    self._body = []

  def process(self):
    self.load()
    self.parse_header()
    self.save()

  def load(self):
    with open(self._path, 'r') as infile:
      self._old_lines = [line.rstrip() for line in infile.read().splitlines()]

  def parse_header(self):
    # Find first non-header-comment line.
    try:
      p = next(i for i, line in enumerate(self._old_lines) if line and not line.startswith('#'))
    except StopIteration:
      return  # File is empty (possibly except for a comment).
    def _translate(line):
      return line.replace('twitter/pants', 'pants').replace('twitter.pants', 'pants').replace(
        'src/python/twitter/common/', '3rdparty/python:twitter.common.'
      )
    self._body = map(_translate, self._old_lines[p:])
    # Remove any trailing empty lines.
    while not self._body[-1]:
      self._body = self._body[0:-1]

  def save(self):
    with open(self._path, 'w') as outfile:
      if self._body:
        for line in HEADER_COMMENT:
          outfile.write(line)
          outfile.write('\n')
        outfile.write('\n')
        for line in self._body:
          outfile.write(line)
          outfile.write('\n')


class PantsSourceFile(object):
  def __init__(self, path):
    self._path = path
    absdir = os.path.dirname(os.path.abspath(path))
    if absdir.startswith(SRC_ROOT):
      root = SRC_ROOT
    elif absdir.startswith(TESTS_ROOT):
      root = TESTS_ROOT
    else:
      raise Exception('File not in src or tests roots: %s' % path)
    self._package = os.path.relpath(absdir, root).replace(os.path.sep, '.')
    self._old_lines = []
    self._stdlib_imports = []
    self._thirdparty_imports = []
    self._pants_imports = []
    self._body = []

  def process(self):
    self.load()
    self.parse_header()
    self.save()

  def is_empty(self):
    return not (self._stdlib_imports or self._thirdparty_imports or self._pants_imports or self._body)

  def load(self):
    with open(self._path, 'r') as infile:
      self._old_lines = [line.rstrip() for line in infile.read().splitlines()]

  def parse_header(self):
    # Strip __author__.
    lines = filter(lambda x: not AUTHOR_RE.match(x), self._old_lines)

    # Find first non-header-comment line.
    try:
      p = next(i for i, line in enumerate(lines) if line and not line.startswith('#'))
    except StopIteration:
      return  # File is empty (possibly except for a comment).

    content_lines = lines[p:]

    def add_import(imp):
      s = imp.package()
      if s.split('.', 1)[0] in KNOWN_STD_LIBS:
        self._stdlib_imports.append(imp)
      elif s.startswith(NEW_PANTS_PACKAGE):
        self._pants_imports.append(imp)
      else:
        self._thirdparty_imports.append(imp)

    def is_import(line):
      m = IMPORT_RE.match(line)
      if m:
        add_import(Import(m.group(1)))
        return True
      else:
        return False

    def is_from_import(line):
      def absify(imp):
        if imp == '.':
          return self._package
        elif imp.startswith('.'):
          return '%s.' % self._package + imp[1:]
        else:
          return imp
      m = FROM_IMPORT_RE.match(line)
      if m:
        if not m.group(1) == '__future__':
          add_import(FromImport(absify(m.group(1)), m.group(2).split(',')))
        return True
      else:
        return False

    # Parse imports.
    lines_iter = iter(content_lines)
    line = ''
    line_parts = []
    try:
      while not line or is_import(line) or is_from_import(line):
        line_parts = [lines_iter.next()]
        while has_continuation(line_parts[-1]):
          line_parts.append(lines_iter.next())
        line = ' '.join([x[:-1].strip() for x in line_parts[:-1]] + [line_parts[-1].strip()])
        if line.startswith('from ') and '(' in line:
          line_parts = [line]
          next_line = ''
          while not ')' in next_line:
            next_line = lines_iter.next().strip()
            line_parts.append(next_line)
          line = ' '.join(line_parts)
    except StopIteration:
      line_parts = []

    def _translate(line):
      return line.replace('twitter/pants', 'pants').replace('twitter.pants', 'pants')
    self._body = map(_translate, [''] + line_parts + list(lines_iter))

    # Remove any trailing empty lines.
    while self._body and not self._body[-1]:
      self._body = self._body[0:-1]

  def save(self):
    sorted_stdlib_imports = map(str, sorted(self._stdlib_imports, key=lambda x: x.sort_key()))
    sorted_thirdparty_imports = map(str, sorted(self._thirdparty_imports, key=lambda x: x.sort_key()))
    sorted_pants_imports = map(str, sorted(self._pants_imports, key=lambda x: x.sort_key()))
    with open(self._path, 'w') as outfile:
      if not self.is_empty():
        for lines in [HEADER_COMMENT, FUTURE_IMPORTS, sorted_stdlib_imports,
                      sorted_thirdparty_imports, sorted_pants_imports]:
          for line in lines:
            outfile.write(line)
            outfile.write('\n')
          if lines:
            outfile.write('\n')
        for line in self._body:
          outfile.write(line)
          outfile.write('\n')


def handle_path(path):
  if os.path.isfile(path):
    if path.endswith('.py') and not path.endswith('pantsbuild_migration.py'):
      print('PROCESSING: %s' % path)
      srcfile = PantsSourceFile(path)
      srcfile.process()
    elif os.path.basename(path).startswith('BUILD'):
      print('PROCESSING: %s' % path)
      srcfile = BuildFile(path)
      srcfile.process()
    elif path.endswith('.rst') or path.endswith('.sh') or path.endswith('pants.bootstrap'):
      print('PROCESSING: %s' % path)
      with open(path, 'r') as infile:
        content = infile.read()
      new_content = content.replace('twitter.pants', 'pants').replace('twitter/pants', 'pants')
      with open(path, 'w') as outfile:
        outfile.write(new_content)
  elif os.path.isdir(path):
    for p in os.listdir(path):
      handle_path(os.path.join(path, p))

if __name__ == '__main__':
  path = sys.argv[1]
  handle_path(path)
