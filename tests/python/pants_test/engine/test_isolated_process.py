# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import tarfile
import unittest

from pants.engine.fs import PathGlobs, Snapshot, create_fs_rules
from pants.engine.isolated_process import (ExecuteProcessRequest, ExecuteProcessResult,
                                           create_process_rules)
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get, Select
from pants.util.objects import TypeCheckError, datatype
from pants_test.engine.scheduler_test_base import SchedulerTestBase


class Concatted(datatype([('value', str)])): pass


class BinaryLocation(datatype(['bin_path'])):

  def __new__(cls, bin_path):
    this_object = super(BinaryLocation, cls).__new__(cls, str(bin_path))

    bin_path = this_object.bin_path

    if os.path.isfile(bin_path) and os.access(bin_path, os.X_OK):
      return this_object

    raise TypeCheckError(
      cls.__name__,
      "path {} does not name an existing executable file.".format(bin_path))


class ShellCat(datatype([('binary_location', BinaryLocation)])):
  """Wrapper class to show an example of using an auxiliary class (which wraps
  an executable) to generate an argv instead of doing it all in
  CatExecutionRequest. This can be used to encapsulate operations such as
  sanitizing command-line arguments which are specific to the executable, which
  can reduce boilerplate for generating ExecuteProcessRequest instances if the
  executable is used in different ways across multiple different types of
  process execution requests."""

  @property
  def bin_path(self):
    return self.binary_location.bin_path

  def argv_from_snapshot(self, snapshot):
    cat_file_paths = [f.path for f in snapshot.files]

    option_like_files = [p for p in cat_file_paths if p.startswith('-')]
    if option_like_files:
      raise ValueError(
        "invalid file names: '{}' look like command-line options"
        .format(option_like_files))

    return (self.bin_path,) + tuple(cat_file_paths)


class CatExecutionRequest(datatype([('shell_cat', ShellCat), ('path_globs', PathGlobs)])): pass


@rule(ExecuteProcessRequest, [Select(CatExecutionRequest)])
def cat_files_process_request_input_snapshot(cat_exe_req):
  cat_bin = cat_exe_req.shell_cat
  cat_files_snapshot = yield Get(Snapshot, PathGlobs, cat_exe_req.path_globs)
  yield ExecuteProcessRequest.create_from_snapshot(
    argv=cat_bin.argv_from_snapshot(cat_files_snapshot),
    env=tuple(),
    snapshot=cat_files_snapshot,
  )


@rule(Concatted, [Select(CatExecutionRequest)])
def cat_files_process_result_concatted(cat_exe_req):
  cat_process_result = yield Get(ExecuteProcessResult, CatExecutionRequest, cat_exe_req)
  yield Concatted(str(cat_process_result.stdout))


def create_cat_stdout_rules():
  return [
    cat_files_process_request_input_snapshot,
    cat_files_process_result_concatted,
    RootRule(CatExecutionRequest),
  ]


class JavacVersionExecutionRequest(datatype([('binary_location', BinaryLocation)])):

  @property
  def bin_path(self):
    return self.binary_location.bin_path

  def gen_argv(self):
    return (self.bin_path, '-version',)


@rule(ExecuteProcessRequest, [Select(JavacVersionExecutionRequest)])
def process_request_from_javac_version(javac_version_exe_req):
  yield ExecuteProcessRequest.create_with_empty_snapshot(
    argv=javac_version_exe_req.gen_argv(),
    env=tuple())


class JavacVersionOutput(datatype([('value', str)])): pass


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


@rule(JavacVersionOutput, [Select(JavacVersionExecutionRequest)])
def get_javac_version_output(javac_version_command):
  javac_version_proc_req = yield Get(
    ExecuteProcessRequest, JavacVersionExecutionRequest, javac_version_command)
  javac_version_proc_result = yield Get(
    ExecuteProcessResult, ExecuteProcessRequest, javac_version_proc_req)

  exit_code = javac_version_proc_result.exit_code
  if exit_code != 0:
    stdout = javac_version_proc_result.stdout
    stderr = javac_version_proc_result.stderr
    # TODO(cosmicexplorer): We should probably make this automatic for most
    # process invocations (see #5719).
    raise ProcessExecutionFailure(
      exit_code, stdout, stderr, 'obtaining javac version')

  yield JavacVersionOutput(str(javac_version_proc_result.stderr))


class JavacSources(datatype([('path_globs', PathGlobs)])):
  """PathGlobs wrapper for Java source files to show an example of making a
  custom type to wrap generic types such as PathGlobs to add usage context.

  See CatExecutionRequest and rules above for an example of using PathGlobs
  which does not introduce this additional layer of indirection.
  """


class JavacCompileRequest(datatype([
    ('binary_location', BinaryLocation),
    ('javac_sources', JavacSources),
])):

  @property
  def bin_path(self):
    return self.binary_location.bin_path

  def argv_from_source_snapshot(self, snapshot):
    snapshot_file_paths = [f.path for f in snapshot.files]

    return (self.bin_path,) + tuple(snapshot_file_paths)


@rule(ExecuteProcessRequest, [Select(JavacCompileRequest)])
def javac_compile_sources_execute_process_request(javac_compile_req):
  sources_snapshot = yield Get(
    Snapshot, PathGlobs, javac_compile_req.javac_sources.path_globs)
  yield ExecuteProcessRequest.create_from_snapshot(
    argv=javac_compile_req.argv_from_source_snapshot(sources_snapshot),
    env=tuple(),
    snapshot=sources_snapshot,
  )


# TODO: make this contain the snapshot(s?) of the output files (or contain
# something that contains it) once we've made it so processes can make snapshots
# of the files they produce.
class JavacCompileResult(object): pass


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
    javac_compile_sources_execute_process_request,
    javac_compile_process_result,
    RootRule(JavacCompileRequest),
  ]


class ExecuteProcessRequestTest(SchedulerTestBase, unittest.TestCase):
  def _default_args_execute_process_request(self, argv=tuple(), env=tuple()):
    return ExecuteProcessRequest.create_with_empty_snapshot(
      argv=argv,
      env=env,
    )

  def test_blows_up_on_invalid_args(self):
    try:
      self._default_args_execute_process_request()
    except ValueError:
      self.assertTrue(False, "should be able to construct without error")

    with self.assertRaises(ValueError):
      self._default_args_execute_process_request(argv=['1'])
    with self.assertRaises(ValueError):
      self._default_args_execute_process_request(argv=('1',), env=[])

    # TODO(cosmicexplorer): we should probably check that the digest info in
    # ExecuteProcessRequest is valid, beyond just checking if it's a string.
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
      ShellCat(BinaryLocation('/bin/cat')),
      PathGlobs.create('', include=['fs_test/a/b/*']))

    self.assertEqual(
      repr(cat_exe_req),
      "CatExecutionRequest(shell_cat=ShellCat(binary_location=BinaryLocation(bin_path='/bin/cat')), path_globs=PathGlobs(include=(u'fs_test/a/b/*',), exclude=()))")

    results = self.execute(scheduler, Concatted, cat_exe_req)
    self.assertEqual(1, len(results))
    concatted = results[0]
    self.assertEqual(Concatted(str('one\ntwo\n')), concatted)

  def test_javac_version_example(self):
    scheduler = self.mk_scheduler_in_example_fs([
      RootRule(JavacVersionExecutionRequest),
      process_request_from_javac_version,
      get_javac_version_output,
    ])

    request = JavacVersionExecutionRequest(BinaryLocation('/usr/bin/javac'))

    self.assertEqual(
      repr(request),
      "JavacVersionExecutionRequest(binary_location=BinaryLocation(bin_path='/usr/bin/javac'))")

    results = self.execute(scheduler, JavacVersionOutput, request)
    self.assertEqual(1, len(results))
    javac_version_output = results[0]
    self.assertIn('javac', javac_version_output.value)

  def test_javac_compilation_example_success(self):
    scheduler = self.mk_scheduler_in_example_fs(create_javac_compile_rules())

    request = JavacCompileRequest(
      BinaryLocation('/usr/bin/javac'),
      JavacSources(PathGlobs.create('', include=[
        'scheduler_inputs/src/java/simple/Simple.java',
      ])))

    self.assertEqual(
      repr(request),
      "JavacCompileRequest(binary_location=BinaryLocation(bin_path='/usr/bin/javac'), javac_sources=JavacSources(path_globs=PathGlobs(include=(u'scheduler_inputs/src/java/simple/Simple.java',), exclude=())))")

    results = self.execute(scheduler, JavacCompileResult, request)
    self.assertEqual(1, len(results))
    # TODO: Test that the output snapshot contains Simple.class at the correct
    # path

  def test_javac_compilation_example_failure(self):
    scheduler = self.mk_scheduler_in_example_fs(create_javac_compile_rules())

    request = JavacCompileRequest(
      BinaryLocation('/usr/bin/javac'),
      JavacSources(PathGlobs.create('', include=[
        'scheduler_inputs/src/java/simple/Broken.java',
      ])))

    self.assertEqual(
      repr(request),
      "JavacCompileRequest(binary_location=BinaryLocation(bin_path='/usr/bin/javac'), javac_sources=JavacSources(path_globs=PathGlobs(include=(u'scheduler_inputs/src/java/simple/Broken.java',), exclude=())))")

    with self.assertRaises(ProcessExecutionFailure) as cm:
      self.execute_raising_throw(scheduler, JavacCompileResult, request)
    e = cm.exception
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
