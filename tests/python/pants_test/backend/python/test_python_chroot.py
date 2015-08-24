# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import subprocess
from contextlib import contextmanager
from textwrap import dedent

from pex.pex_builder import PEXBuilder
from pex.platforms import Platform

from pants.backend.codegen.targets.python_antlr_library import PythonAntlrLibrary
from pants.backend.codegen.targets.python_thrift_library import PythonThriftLibrary
from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.python_chroot import PythonChroot
from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.python_setup import PythonRepos, PythonSetup
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.base.source_root import SourceRoot
from pants.binaries.thrift_binary import ThriftBinary
from pants.ivy.bootstrapper import Bootstrapper
from pants.ivy.ivy_subsystem import IvySubsystem
from pants.util.contextutil import temporary_dir
from pants_test.base_test import BaseTest
from pants_test.subsystem.subsystem_util import create_subsystem, subsystem_instance


def test_get_current_platform():
  expected_platforms = [Platform.current(), 'linux-x86_64']
  assert set(expected_platforms) == set(PythonChroot.get_platforms(['current', 'linux-x86_64']))


class PythonChrootTest(BaseTest):

  def setUp(self):
    # Capture PythonSetup with the real BUILD_ROOT before that is reset to a tmpdir by super.
    with subsystem_instance(PythonSetup) as python_setup:
      self.python_setup = python_setup

    super(PythonChrootTest, self).setUp()

  @contextmanager
  def dumped_chroot(self, targets):
    python_repos = create_subsystem(PythonRepos)

    with subsystem_instance(IvySubsystem) as ivy_subsystem:
      ivy_bootstrapper = Bootstrapper(ivy_subsystem=ivy_subsystem)

      with subsystem_instance(ThriftBinary.Factory) as thrift_binary_factory:
        interpreter_cache = PythonInterpreterCache(self.python_setup, python_repos)
        interpreter_cache.setup()
        interpreters = list(interpreter_cache.matched_interpreters([self.python_setup.interpreter_requirement]))
        self.assertGreater(len(interpreters), 0)
        interpreter = interpreters[0]

        with temporary_dir() as chroot:
          pex_builder = PEXBuilder(path=chroot, interpreter=interpreter)

          python_chroot = PythonChroot(python_setup=self.python_setup,
                                       python_repos=python_repos,
                                       ivy_bootstrapper=ivy_bootstrapper,
                                       thrift_binary_factory=thrift_binary_factory.create,
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
    SourceRoot.register('src/antlr', PythonThriftLibrary)
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

    SourceRoot.register('src/python', PythonBinary)
    antlr3 = self.make_target(spec='3rdparty/python:antlr3',
                              target_type=PythonRequirementLibrary,
                              requirements=[PythonRequirement('antlr_python_runtime==3.1.3')])
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
  def do_test_thrift(self):
    SourceRoot.register('src/thrift', PythonThriftLibrary)
    self.create_file(relpath='src/thrift/test/const.thrift', contents=dedent("""
      namespace py test

      const list<string> VALID_IDENTIFIERS = ["Hello", "World!"]
    """))
    thrift_target = self.make_target(spec='src/thrift/test',
                                     target_type=PythonThriftLibrary,
                                     sources=['const.thrift'])

    SourceRoot.register('src/python', PythonBinary)
    self.create_file(relpath='src/python/test/main.py', contents=dedent("""
      from test.constants import VALID_IDENTIFIERS


      def say_hello():
        print(' '.join(VALID_IDENTIFIERS))
    """))
    binary = self.make_target(spec='src/python/test',
                              target_type=PythonBinary,
                              source='main.py',
                              dependencies=[thrift_target])

    yield binary, thrift_target

    with self.dumped_chroot([binary]) as (pex_builder, python_chroot):
      pex_builder.set_entry_point('test.main:say_hello')
      pex_builder.freeze()
      pex = python_chroot.pex()

      process = pex.run(blocking=False, stdout=subprocess.PIPE)
      stdout, _ = process.communicate()

      self.assertEqual(0, process.returncode)
      self.assertEqual('Hello World!', stdout.strip())

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
      SourceRoot.register('.synthetic', PythonLibrary)
      self.create_file(relpath='.synthetic/test/__init__.py')
      self.create_file(relpath='.synthetic/test/constants.py', contents=dedent("""
        VALID_IDENTIFIERS = ['generated', 'by', 'upstream', 'and', 'different!']
      """))
      synthetic_pythrift_codegen_target = self.make_target(spec='.synthetic/test:constants',
                                                           target_type=PythonLibrary,
                                                           sources=['__init__.py', 'constants.py'],
                                                           derived_from=thrift_target)
      binary.inject_dependency(synthetic_pythrift_codegen_target.address)
