# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess
from contextlib import contextmanager
from textwrap import dedent

from pex.pex_builder import PEXBuilder
from pex.platforms import Platform

from pants.backend.codegen.antlr.python.python_antlr_library import PythonAntlrLibrary
from pants.backend.codegen.thrift.python.python_thrift_library import PythonThriftLibrary
from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.python_chroot import PythonChroot
from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.binaries.binary_util import BinaryUtil
from pants.binaries.thrift_binary import ThriftBinary
from pants.ivy.bootstrapper import Bootstrapper
from pants.ivy.ivy_subsystem import IvySubsystem
from pants.java.distribution.distribution import DistributionLocator
from pants.python.python_repos import PythonRepos
from pants.util.contextutil import temporary_dir
from pants_test.base_test import BaseTest
from pants_test.subsystem.subsystem_util import global_subsystem_instance


def test_get_current_platform():
  expected_platforms = [Platform.current(), 'linux-x86_64']
  assert set(expected_platforms) == set(PythonChroot.get_platforms(['current', 'linux-x86_64']))


class PythonChrootTest(BaseTest):

  def setUp(self):
    # Capture PythonSetup with the real BUILD_ROOT before that is reset to a tmpdir by super.
    self.python_setup = global_subsystem_instance(PythonSetup)
    super(PythonChrootTest, self).setUp()

  @contextmanager
  def dumped_chroot(self, targets):
    # TODO(benjy): We shouldn't need to mention DistributionLocator here, as IvySubsystem
    # declares it as a dependency. However if we don't then test_antlr() below fails on
    # uninitialized options for that subsystem.  Hopefully my pending (as of 9/2016) change
    # to clean up how we initialize and create instances of subsystems in tests will make
    # this problem go away.
    self.context(for_subsystems=[PythonRepos, PythonSetup, IvySubsystem,
                                 DistributionLocator, ThriftBinary.Factory, BinaryUtil.Factory])
    python_repos = PythonRepos.global_instance()
    ivy_bootstrapper = Bootstrapper(ivy_subsystem=IvySubsystem.global_instance())
    thrift_binary_factory = ThriftBinary.Factory.global_instance().create

    interpreter_cache = PythonInterpreterCache(self.python_setup, python_repos)
    interpreter_cache.setup()
    interpreters = list(interpreter_cache.matched_interpreters(
      self.python_setup.interpreter_constraints))
    self.assertGreater(len(interpreters), 0)
    interpreter = interpreters[0]

    with temporary_dir() as chroot:
      pex_builder = PEXBuilder(path=chroot, interpreter=interpreter)

      python_chroot = PythonChroot(python_setup=self.python_setup,
                                   python_repos=python_repos,
                                   ivy_bootstrapper=ivy_bootstrapper,
                                   thrift_binary_factory=thrift_binary_factory,
                                   interpreter=interpreter,
                                   builder=pex_builder,
                                   targets=targets,
                                   platforms=['current'])
      try:
        python_chroot.dump()
        yield pex_builder, python_chroot
      finally:
        python_chroot.delete()

  def test_antlr(self):
    self.create_file(relpath='src/antlr/word/word.g', contents=dedent("""
      grammar word;

      options {
        language=Python;
        output=AST;
      }

      WORD: ('a'..'z'|'A'..'Z'|'!')+;

      word_up: WORD (' ' WORD)*;
    """))
    antlr_target = self.make_target(spec='src/antlr/word',
                                    target_type=PythonAntlrLibrary,
                                    antlr_version='3.1.3',
                                    sources=['word.g'],
                                    module='word')

    # TODO: see 3rdparty/python/BUILD
    antlr3_requirement = PythonRequirement('antlr_python_runtime==3.1.3',
                                           repository='http://www.antlr3.org/download/Python/')
    antlr3 = self.make_target(spec='3rdparty/python:antlr3',
                              target_type=PythonRequirementLibrary,
                              requirements=[antlr3_requirement])
    self.create_file(relpath='src/python/test/main.py', contents=dedent("""
      import antlr3

      from word import wordLexer, wordParser


      def word_up():
        input = 'Hello World!'
        char_stream = antlr3.ANTLRStringStream(input)
        lexer = wordLexer.wordLexer(char_stream)
        tokens = antlr3.CommonTokenStream(lexer)
        parser = wordParser.wordParser(tokens)

        def print_node(node):
          print(node.text)
        visitor = antlr3.tree.TreeVisitor()
        visitor.visit(parser.word_up().tree, pre_action=print_node)
    """))
    binary = self.make_target(spec='src/python/test',
                              target_type=PythonBinary,
                              source='main.py',
                              dependencies=[antlr_target, antlr3])

    with self.dumped_chroot([binary]) as (pex_builder, python_chroot):
      pex_builder.set_entry_point('test.main:word_up')
      pex_builder.freeze()
      pex = python_chroot.pex()

      process = pex.run(blocking=False, stdout=subprocess.PIPE)
      stdout, _ = process.communicate()

      self.assertEqual(0, process.returncode)
      self.assertEqual(['Hello', ' ', 'World!'], stdout.splitlines())

  @contextmanager
  def do_test_thrift(self, inspect_chroot=None):
    self.create_file(relpath='src/thrift/core/identifiers.thrift', contents=dedent("""
      namespace py core

      const string HELLO = "Hello"
      const string WORLD = "World!"
    """))
    core_const = self.make_target(spec='src/thrift/core',
                                  target_type=PythonThriftLibrary,
                                  sources=['identifiers.thrift'])

    self.create_file(relpath='src/thrift/test/const.thrift', contents=dedent("""
      namespace py test

      include "core/identifiers.thrift"

      const list<string> MESSAGE = [identifiers.HELLO, identifiers.WORLD]
    """))
    test_const = self.make_target(spec='src/thrift/test',
                                  target_type=PythonThriftLibrary,
                                  sources=['const.thrift'],
                                  dependencies=[core_const])

    self.create_file(relpath='src/python/test/main.py', contents=dedent("""
      from test.constants import MESSAGE


      def say_hello():
        print(' '.join(MESSAGE))
    """))
    binary = self.make_target(spec='src/python/test',
                              target_type=PythonBinary,
                              source='main.py',
                              dependencies=[test_const])

    yield binary, test_const

    with self.dumped_chroot([binary]) as (pex_builder, python_chroot):
      pex_builder.set_entry_point('test.main:say_hello')
      pex_builder.freeze()
      pex = python_chroot.pex()

      process = pex.run(blocking=False, stdout=subprocess.PIPE)
      stdout, _ = process.communicate()

      self.assertEqual(0, process.returncode)
      self.assertEqual('Hello World!', stdout.strip())

      if inspect_chroot:
        # Snap a clean copy of the chroot with just the chroots added files.
        chroot = pex_builder.clone().path()
        inspect_chroot(chroot)

  def test_thrift(self):
    with self.do_test_thrift():
      pass  # Run the test on a standard isolated pure python target graph.

  def test_thrift_issues_1858(self):
    # Confirm a synthetic target for our python_thrift_library from some upstream task does not
    # trample the PythonChroot/PythonThriftBuilder generated code.
    # In https://github.com/pantsbuild/pants/issues/1858 the ApacheThriftGen task in the 'gen'
    # phase upstream of the 'binary' goal was injecting a synthetic python_library target owning
    # thrift generated code _and_ that code was a subset of all the code generated by thrift; ie:
    # there was a synthetic python_library being added directly to the chroot missing some thrift
    # codegened '.py' files, leading to import of those files (and errors) instead of the
    # PythonChroot/PythonThriftBuilder generated files (packaged as deps in the PythonChroot).
    with self.do_test_thrift() as (binary, thrift_target):
      self.create_file(relpath='.synthetic/test/python/__init__.py')
      self.create_file(relpath='.synthetic/test/python/constants.py', contents=dedent("""
        VALID_IDENTIFIERS = ['generated', 'by', 'upstream', 'and', 'different!']
      """))
      synthetic_pythrift_codegen_target = self.make_target(spec='.synthetic/test/python:constants',
                                                           target_type=PythonLibrary,
                                                           sources=['__init__.py', 'constants.py'],
                                                           derived_from=thrift_target)
      binary.inject_dependency(synthetic_pythrift_codegen_target.address)

  def test_thrift_issues_2005(self):
    # Issue #2005 highlighted the fact the PythonThriftBuilder was building both a given
    # PythonThriftLibrary's thrift files as well as its transitive dependencies thrift files.
    # We test here that the generated chroot only contains 1 copy of each thrift stub in the face
    # of transitive thrift deps.
    def inspect_chroot(chroot):
      all_constants_files = set()
      for root, _, files in os.walk(chroot):
        all_constants_files.update(os.path.join(root, f) for f in files if f == 'constants.py')

      # If core/constants.py was included in test/ we'd have 2 copies of core/constants.py plus
      # test/constants.py for a total of 3 constants.py files.
      self.assertEqual(2, len(all_constants_files))

    with self.do_test_thrift(inspect_chroot=inspect_chroot):
      pass  # Our test takes place in inspect_chroot above
