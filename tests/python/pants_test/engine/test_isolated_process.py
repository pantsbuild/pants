# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import tarfile
import unittest

from twitter.common.collections import OrderedSet

from pants.engine.fs import PathGlobs, Snapshot, create_fs_rules
from pants.engine.isolated_process import (
  Binary, ExecuteProcessRequest, ExecuteProcessResult, create_process_rules)
from pants.engine.nodes import Return, Throw
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get, Select
from pants.util.objects import datatype
from pants_test.engine.scheduler_test_base import SchedulerTestBase


class Concatted(datatype('Concatted', ['value'])):
  pass


class ShellCat(Binary):
  @property
  def bin_path(self):
    return '/bin/cat'

  def gen_argv(self, snapshots):
    cat_file_paths = []
    for s in snapshots:
      cat_file_paths.extend(f.path for f in s.files)
    # TODO(cosmicexplorer): We should have a structured way to create command
    # lines which properly escape e.g. file arguments which would be parsed as
    # options, for greater security and usability. This should probably be
    # composable (see Javac and its subclasses below).
    return (self.bin_path,) + tuple(cat_file_paths)


class CatExecutionRequest(datatype('CatExecutionRequest', [
    'shell_cat_binary',
    'input_file_globs',
])):

  def __new__(cls, shell_cat_binary, input_file_globs):
    if not isinstance(shell_cat_binary, ShellCat):
      raise ValueError('shell_cat_binary should be an instance of ShellCat')
    if not isinstance(input_file_globs, PathGlobs):
      raise ValueError(
        'input_file_globs should be an instance of PathGlobs')

    return super(CatExecutionRequest, cls).__new__(
      cls, shell_cat_binary, input_file_globs)


@rule(ExecuteProcessRequest, [Select(CatExecutionRequest)])
def cat_files_process_request_input_snapshot(cat_exe_req):
  cat_bin = cat_exe_req.shell_cat_binary
  cat_files_snapshot = yield Get(Snapshot, PathGlobs, cat_exe_req.input_file_globs)
  yield ExecuteProcessRequest.create_from_snapshot(
    argv=cat_bin.gen_argv([cat_files_snapshot]),
    env=tuple(),
    snapshot=cat_files_snapshot,
  )


@rule(Concatted, [Select(CatExecutionRequest)])
def cat_files_process_result_concatted(cat_exe_req):
  # FIXME(cosmicexplorer): we should only have to run Get once here. this:
  # yield Get(ExecuteProcessResult, CatExecutionRequest, cat_exe_req)
  # fails because ExecuteProcessRequest is a RootRule (which shouldn't be true),
  # but there's some work required in isolated_process.py to fix this.
  cat_proc_req = yield Get(ExecuteProcessRequest, CatExecutionRequest, cat_exe_req)
  cat_process_result = yield Get(ExecuteProcessResult, ExecuteProcessRequest, cat_proc_req)
  yield Concatted(value=cat_process_result.stdout)


def create_cat_stdout_rules():
  return [
    cat_files_process_request_input_snapshot,
    cat_files_process_result_concatted,
    RootRule(CatExecutionRequest),
  ]


class JavaOutputDir(datatype('JavaOutputDir', ['path'])):
  pass


class Javac(Binary):

  @property
  def bin_path(self):
    return '/usr/bin/javac'


class JavacVersionCommand(Javac):

  def gen_argv(self):
    return (self.bin_path, '-version',)


@rule(ExecuteProcessRequest, [Select(JavacVersionCommand)])
def process_request_from_javac_version(javac_version_command):
  yield ExecuteProcessRequest.create_with_empty_snapshot(
    argv=javac_version_command.gen_argv(),
    env=tuple())


class JavacVersionOutput(datatype('JavacVersionOutput', ['version_output'])):
  pass


class ProcessExecutionFailure(Exception):
  """Used to denote that a process exited, but was unsuccessful in some way.

  For example, exiting with a non-zero code.
  """

  MSG_FMT = """process '{desc}' failed with code {code}.
stdout:
{stdout}
stderr:
{stderr}
"""

  def __init__(self, exit_code, stdout, stderr, process_description):
    # These are intentionally "public" members.
    self.exit_code = exit_code
    self.stdout = stdout
    self.stderr = stderr

    msg = self.MSG_FMT.format(
      desc=process_description, code=exit_code, stdout=stdout, stderr=stderr)

    super(ProcessExecutionFailure, self).__init__(msg)


@rule(JavacVersionOutput, [Select(JavacVersionCommand)])
def get_javac_version_output(javac_version_command):
  javac_version_proc_req = yield Get(
    ExecuteProcessRequest, JavacVersionCommand, javac_version_command)
  javac_version_proc_result = yield Get(
    ExecuteProcessResult, ExecuteProcessRequest, javac_version_proc_req)

  exit_code = javac_version_proc_result.exit_code
  if exit_code != 0:
    stdout = javac_version_proc_result.stdout
    stderr = javac_version_proc_result.stderr
    raise ProcessExecutionFailure(
      exit_code, stdout, stderr, 'obtaining javac version')

  yield JavacVersionOutput(
    version_output=javac_version_proc_result.stderr,
  )


class JavacCompileCommand(Javac):

  def gen_argv(self, snapshots):
    # TODO(cosmicexplorer): We use an OrderedSet here to dedup file entries --
    # should we be allowing different snapshots to have overlapping file paths
    # when exposing them in python?
    snapshot_file_paths = OrderedSet()
    for s in snapshots:
      for f in s.files:
        snapshot_file_paths.add(f.path)

    return (self.bin_path,) + tuple(snapshot_file_paths)


class JavacSources(datatype('JavacSources', ['globs'])):
  """PathGlobs wrapper for Java source files to show an example of making a
  custom type to wrap generic types such as PathGlobs to add usage context.

  See CatExecutionRequest and rules above for an example of using PathGlobs
  which does not introduce this additional layer of indirection.
  """

  def __new__(cls, globs):

    if not isinstance(globs, PathGlobs):
      raise ValueError('globs should be an instance of PathGlobs')

    return super(JavacSources, cls).__new__(cls, globs)


@rule(PathGlobs, [Select(JavacSources)])
def javac_sources_to_globs(javac_sources):
  yield javac_sources.globs


class JavacCompileRequest(datatype('JavacCompileRequest', [
    'javac_compile_command',
    'javac_sources',
])):

  def __new__(cls, javac_compile_command, javac_sources):

    if not isinstance(javac_compile_command, JavacCompileCommand):
      raise ValueError(
        'javac_compile_command should be an instance of JavacCompileCommand')
    if not isinstance(javac_sources, JavacSources):
      raise ValueError(
        'javac_sources should be an instance of JavacSources')

    return super(JavacCompileRequest, cls).__new__(
      cls, javac_compile_command, javac_sources)


@rule(ExecuteProcessRequest, [Select(JavacCompileRequest)])
def javac_compile_sources_execute_process_request(javac_compile_req):
  javac_compiler = javac_compile_req.javac_compile_command
  sources_snapshot = yield Get(
    Snapshot, JavacSources, javac_compile_req.javac_sources)
  yield ExecuteProcessRequest.create_from_snapshot(
    argv=javac_compiler.gen_argv([sources_snapshot]),
    env=tuple(),
    snapshot=sources_snapshot,
  )


# TODO: make this contain the snapshot(s?) of the output files (or contain
# something that contains it) once we've made it so processes can make snapshots
# of the files they produce.
class JavacCompileResult(datatype('JavacCompileResult', [])):
  pass


@rule(JavacCompileResult, [Select(JavacCompileRequest)])
def javac_compile_process_result(javac_compile_req):
  javac_proc_req = yield Get(
    ExecuteProcessRequest, JavacCompileRequest, javac_compile_req)
  javac_proc_result = yield Get(
    ExecuteProcessResult, ExecuteProcessRequest, javac_proc_req)

  exit_code = javac_proc_result.exit_code
  if exit_code != 0:
    stdout = javac_proc_result.stdout
    stderr = javac_proc_result.stderr
    raise ProcessExecutionFailure(
      exit_code, stdout, stderr, 'javac compilation')

  yield JavacCompileResult()


def create_javac_compile_rules():
  return [
    javac_sources_to_globs,
    javac_compile_sources_execute_process_request,
    javac_compile_process_result,
    RootRule(JavacCompileRequest),
  ]


class ExecuteProcessRequestTest(SchedulerTestBase, unittest.TestCase):
  def test_blows_up_on_invalid_args(self):
    with self.assertRaises(ValueError):
      ExecuteProcessRequest(argv=['1'], env=tuple(), input_files_digest='', digest_length=0)
    with self.assertRaises(ValueError):
      ExecuteProcessRequest(argv=('1',), env=[], input_files_digest='', digest_length=0)
    with self.assertRaises(ValueError):
      ExecuteProcessRequest(argv=('1',), env=tuple(), input_files_digest='', digest_length='')
    with self.assertRaises(ValueError):
      ExecuteProcessRequest(argv=('1',), env=tuple(), input_files_digest=3, digest_length=0)
    with self.assertRaises(ValueError):
      ExecuteProcessRequest(argv=('1',), env=tuple(), input_files_digest='', digest_length=-1)


class IsolatedProcessTest(SchedulerTestBase, unittest.TestCase):

  def test_integration_concat_with_snapshots_stdout(self):
    scheduler = self.mk_scheduler_in_example_fs(create_cat_stdout_rules())

    cat_exe_req = CatExecutionRequest(
      shell_cat_binary=ShellCat(),
      input_file_globs=PathGlobs.create('', include=['fs_test/a/b/*']),
    )

    results = self.execute(scheduler, Concatted, cat_exe_req)
    self.assertEquals(1, len(results))
    concatted = results[0]
    self.assertEqual(Concatted('one\ntwo\n'), concatted)

  def test_javac_version_example(self):
    scheduler = self.mk_scheduler_in_example_fs([
      RootRule(JavacVersionCommand),
      process_request_from_javac_version,
      get_javac_version_output,
    ])
    results = self.execute(scheduler, JavacVersionOutput, JavacVersionCommand())
    self.assertEquals(1, len(results))
    javac_version_output = results[0]
    self.assertIn('javac', javac_version_output.version_output)

  def test_javac_compilation_example_success(self):
    javac_sources = JavacSources(PathGlobs.create('', include=[
      'scheduler_inputs/src/java/simple/Simple.java',
    ]))

    scheduler = self.mk_scheduler_in_example_fs(create_javac_compile_rules())

    request = JavacCompileRequest(
      javac_compile_command=JavacCompileCommand(),
      javac_sources=javac_sources,
    )

    results = self.execute(scheduler, JavacCompileResult, request)
    self.assertEquals(1, len(results))
    # TODO: Test that the output snapshot contains Simple.class at the correct
    # path

  def test_javac_compilation_example_failure(self):
    javac_sources = JavacSources(PathGlobs.create('', include=[
      'scheduler_inputs/src/java/simple/Broken.java',
    ]))

    scheduler = self.mk_scheduler_in_example_fs(create_javac_compile_rules())

    request = JavacCompileRequest(
      javac_compile_command=JavacCompileCommand(),
      javac_sources=javac_sources,
    )

    try:
      result = self.execute_raising_throw(scheduler, JavacCompileResult, request)
      raise Exception("error: should have thrown (result: '{}')"
                      .format(repr(result)))
    except ProcessExecutionFailure as e:
      self.assertEqual(1, e.exit_code)
      self.assertIn("NOT VALID JAVA", e.stderr)

  def mk_example_fs_tree(self):
    fs_tree = self.mk_fs_tree(os.path.join(os.path.dirname(__file__), 'examples'))
    test_fs = os.path.join(fs_tree.build_root, 'fs_test')
    with tarfile.open(os.path.join(test_fs, 'fs_test.tar')) as tar:
      tar.extractall(test_fs)
    return fs_tree

  def mk_scheduler_in_example_fs(self, rules):
    rules = list(rules) + create_fs_rules() + create_process_rules()
    return self.mk_scheduler(rules=rules, project_tree=self.mk_example_fs_tree())
