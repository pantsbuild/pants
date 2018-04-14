# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import tarfile
import unittest

from pants.engine.fs import PathGlobs, Snapshot, create_fs_rules
from pants.engine.isolated_process import (
  Binary, ExecuteProcess, ExecuteProcessRequest, ExecuteProcessResult,
  SnapshottedProcess, SnapshottedProcessRequest, SnapshottedProcessResult,
  create_process_rules)
from pants.engine.nodes import Return, Throw
from pants.engine.rules import RootRule, SingletonRule, rule
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
    # TODO: ensure everything is a real path?
    return (self.bin_path,) + tuple(cat_file_paths)


class CatSourceFiles(datatype('CatSourceFiles', [
    'globs',
])):

  def __new__(cls, globs):

    if not isinstance(globs, PathGlobs):
      raise ValueError('globs should be an instance of PathGlobs')

    return super(CatSourceFiles, cls).__new__(cls, globs)

  def as_path_globs(self):
    return self.globs


@rule(PathGlobs, [Select(CatSourceFiles)])
def cat_source_to_globs(cat_src):
  yield cat_src.as_path_globs()


class CatExecutionRequest(datatype('CatExecutionRequest', [
    'shell_cat_binary',
    'cat_source_files',
])): pass


@rule(SnapshottedProcessRequest, [Select(CatExecutionRequest)])
def cat_files_snapshotted_process_request(cat_exe_req):
  cat_bin = cat_exe_req.shell_cat_binary
  cat_src = cat_exe_req.cat_source_files
  cat_files_snapshot = yield Get(Snapshot, CatSourceFiles, cat_src)
  yield SnapshottedProcessRequest(
    binary=cat_bin,
    input_snapshots=(cat_files_snapshot,),
  )


@rule(Concatted, [Select(CatExecutionRequest)])
def cat_files_process_result_concatted(cat_exe_req):
  cat_process_result = yield Get(SnapshottedProcessResult, CatExecutionRequest, cat_exe_req)
  yield Concatted(value=cat_process_result.stdout)


def file_list_to_args_for_cat_with_snapshot_subjects_and_output_file(snapshot):
  return SnapshottedProcessRequest(args=tuple(sorted(f.path for f in snapshot.files)),
    snapshots=(snapshot,))


def process_result_to_concatted_from_outfile(process_result, sandbox_dir):
  with open(os.path.join(sandbox_dir, 'outfile')) as f:
    # TODO might be better to allow for this to be done via Nodes. But I'm not sure how as yet.
    return Concatted(f.read())


def process_result_to_concatted(process_result, sandbox_dir):
  return Concatted(process_result.stdout)


class ShellCatToOutFile(Binary):
  OUTPUT_FILE_PATH = 'outfile'

  def prefix_of_command(self):
    return tuple([
      'sh',
      '-c',
      'cat $@ > {}'.format(self.OUTPUT_FILE_PATH),
      'unused',
    ])

  def expected_output_path_globs(self):
    return PathGlobs.create(relative_to='', include=[self.OUTPUT_FILE_PATH])


class ShellFailCommand(Binary):
  def prefix_of_command(self):
    return tuple(['sh', '-c', 'exit 1'])

  def __repr__(self):
    return 'ShellFailCommand'


def fail_process_result(process_result, sandbox_dir):
  raise Exception('Failed in output conversion!')


def empty_process_request():
  return SnapshottedProcessRequest(args=tuple())


class JavaOutputDir(datatype('JavaOutputDir', ['path'])):
  pass


class Javac(Binary):

  @property
  def bin_path(self):
    return '/usr/bin/javac'


def java_sources_to_javac_args(sources_snapshot, out_dir):
  return SnapshottedProcessRequest(args=('-d', out_dir.path)+
                                        tuple(f.path for f in sources_snapshot.files),
                                   snapshots=(sources_snapshot,),
                                   directories_to_create=(out_dir.path,))


def process_request_from_java_sources(binary):
  env = []
  return ExecuteProcessRequest(
    argv=binary.prefix_of_command() + ('-version',),
    env=env,
    input_files_digest="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    digest_length=0)


def process_request_java_args_from_java_sources(binary, sources_snapshot, out_dir):
  env = []
  return ExecuteProcessRequest(
    argv=binary.prefix_of_command() + tuple(f.path for f in sources_snapshot.files),
    input_files_digest=str(sources_snapshot.fingerprint),
    digest_length=sources_snapshot.digest_length,
    env=env)


class ClasspathEntry(datatype('ClasspathEntry', ['path'])):
  """A classpath entry for a subject."""


def process_result_to_classpath_entry(process_result, sandbox_dir):
  if not process_result.exit_code:
    # this implies that we should pass some / all of the inputs to the output conversion so they
    # can grab config.
    # TODO string name association isn't great.
    return ClasspathEntry(os.path.join(sandbox_dir, 'build'))


def execute_process_result_to_classpath(process_result, sandbox_dir):
  if not process_result.exit_code:
    return ClasspathEntry(os.path.join(sandbox_dir, 'build'))


class SnapshottedProcessRequestTest(SchedulerTestBase, unittest.TestCase):
  def test_blows_up_on_unhashable_args(self):
    with self.assertRaises(ValueError):
      SnapshottedProcessRequest(args=['1'])
    with self.assertRaises(ValueError):
      SnapshottedProcessRequest(args=('1',), snapshots=[])
    with self.assertRaises(ValueError):
      SnapshottedProcessRequest(args=('1',), directories_to_create=[])


class IsolatedProcessTest(SchedulerTestBase, unittest.TestCase):

  def test_integration_concat_with_snapshots_stdout(self):
    scheduler = self.mk_scheduler_in_example_fs([
      RootRule(CatExecutionRequest),
      cat_source_to_globs,
      cat_files_snapshotted_process_request,
      cat_files_process_result_concatted,
    ])

    cat_src_files = CatSourceFiles(
      PathGlobs.create('', include=['fs_test/a/b/*']))
    cat_exe_req = CatExecutionRequest(
      shell_cat_binary=ShellCat(),
      cat_source_files=cat_src_files,
    )

    results = self.execute(scheduler, Concatted, cat_exe_req)
    self.assertEquals(1, len(results))
    concatted = results[0].value

    self.assertEqual(Concatted('one\ntwo\n', concatted))

  # TODO: Re-write this test to work with non-tar-file snapshots
  @unittest.skip
  def test_integration_concat_with_snapshot_subjects_test(self):
    scheduler = self.mk_scheduler_in_example_fs([
      # subject to files / product of subject to files for snapshot.
      SnapshottedProcess.create(product_type=Concatted,
        binary_type=ShellCatToOutFile,
        input_selectors=(Select(Snapshot),),
        input_conversion=file_list_to_args_for_cat_with_snapshot_subjects_and_output_file,
        output_conversion=process_result_to_concatted_from_outfile),
      SingletonRule(ShellCatToOutFile, ShellCatToOutFile()),
    ])

    request = scheduler.execution_request([Concatted],
      [PathGlobs.create('', include=['fs_test/a/b/*'])])
    root_entries = scheduler.execute(request).root_products
    self.assertEquals(1, len(root_entries))
    state = self.assertFirstEntryIsReturn(root_entries, scheduler, request)
    concatted = state.value

    self.assertEqual(Concatted('one\ntwo\n'), concatted)

  def test_javac_version_example(self):
    sources = PathGlobs.create('', include=['inputs/src/java/simple/Simple.java'])
    scheduler = self.mk_scheduler_in_example_fs([
      ExecuteProcess.create_in(product_type=ExecuteProcessRequest,
        input_selectors=(Select(Javac),),
        input_conversion=process_request_from_java_sources),
      SingletonRule(Javac, Javac()),
    ])
    req = scheduler.product_request(ExecuteProcessRequest, [sources])
    request = scheduler.execution_request([ExecuteProcessResult], req)
    root_entries = scheduler.execute(request).root_products

    self.assertEquals(1, len(root_entries))
    state = self.assertFirstEntryIsReturn(root_entries, scheduler, request)
    result = state.value
    self.assertEqual(0, result.exit_code)
    self.assertIn('javac', result.stderr)

  # TODO: Re-write this test to work with non-tar-file snapshots
  @unittest.skip
  def test_javac_compilation_example(self):
    sources = PathGlobs.create('', include=['scheduler_inputs/src/java/simple/Simple.java'])

    scheduler = self.mk_scheduler_in_example_fs([
      SnapshottedProcess.create(ClasspathEntry,
        Javac,
        (Select(Snapshot), Select(JavaOutputDir)),
        java_sources_to_javac_args,
        process_result_to_classpath_entry),
      SingletonRule(JavaOutputDir, JavaOutputDir('build')),
      SingletonRule(Javac, Javac()),
    ])

    request = scheduler.execution_request(
      [ClasspathEntry],
      [sources])
    root_entries = scheduler.execute(request).root_products

    self.assertEquals(1, len(root_entries))
    state = self.assertFirstEntryIsReturn(root_entries, scheduler, request)
    classpath_entry = state.value
    self.assertIsInstance(classpath_entry, ClasspathEntry)
    self.assertTrue(os.path.exists(os.path.join(classpath_entry.path, 'simple', 'Simple.class')))

  def test_javac_compilation_example_rust_success(self):
    sources = PathGlobs.create('', include=['scheduler_inputs/src/java/simple/Simple.java'])

    scheduler = self.mk_scheduler_in_example_fs([
      ExecuteProcess.create_in(
        product_type=ExecuteProcessRequest,
        input_selectors=(Select(Javac), Select(Snapshot), Select(JavaOutputDir)),
        input_conversion=process_request_java_args_from_java_sources),
      SingletonRule(JavaOutputDir, JavaOutputDir('testing')),
      SingletonRule(Javac, Javac()),
    ])
    req = scheduler.product_request(ExecuteProcessRequest, [sources])
    request = scheduler.execution_request([ExecuteProcessResult], req)

    root_entries = scheduler.execute(request).root_products
    self.assertEquals(1, len(root_entries))
    state = self.assertFirstEntryIsReturn(root_entries, scheduler, request)
    execution_result = state.value
    self.assertEqual(0, execution_result.exit_code)
    # TODO: Test that the output snapshot is good

  def test_javac_compilation_example_rust_failure(self):
    sources = PathGlobs.create('', include=['scheduler_inputs/src/java/simple/Broken.java'])

    scheduler = self.mk_scheduler_in_example_fs([
      ExecuteProcess.create_in(
        product_type=ExecuteProcessRequest,
        input_selectors=(Select(Javac), Select(Snapshot), Select(JavaOutputDir)),
        input_conversion=process_request_java_args_from_java_sources),
      SingletonRule(JavaOutputDir, JavaOutputDir('testing')),
      SingletonRule(Javac, Javac()),
    ])
    req = scheduler.product_request(ExecuteProcessRequest, [sources])
    request = scheduler.execution_request([ExecuteProcessResult], req)

    root_entries = scheduler.execute(request).root_products
    self.assertEquals(1, len(root_entries))
    state = self.assertFirstEntryIsReturn(root_entries, scheduler, request)
    execution_result = state.value
    self.assertEqual(1, execution_result.exit_code)
    self.assertIn("NOT VALID JAVA", execution_result.stderr)

  def test_failed_command_propagates_throw(self):
    scheduler = self.mk_scheduler_in_example_fs([
      # subject to files / product of subject to files for snapshot.
      SnapshottedProcess.create(product_type=Concatted,
                                binary_type=ShellFailCommand,
                                input_selectors=tuple(),
                                input_conversion=empty_process_request,
                                output_conversion=fail_process_result),
      SingletonRule(ShellFailCommand, ShellFailCommand()),
    ])

    request = scheduler.execution_request([Concatted],
                                          [PathGlobs.create('', include=['fs_test/a/b/*'])])
    root_entries = scheduler.execute(request).root_products

    self.assertEquals(1, len(root_entries))
    self.assertFirstEntryIsThrow(root_entries,
                                 in_msg='Running ShellFailCommand failed with non-zero exit code: 1')

  # TODO: Enable a test when input/output conversions are worked out
  @unittest.skip
  def test_failed_output_conversion_propagates_throw(self):
    scheduler = self.mk_scheduler_in_example_fs([
      # subject to files / product of subject to files for snapshot.
      SnapshottedProcess.create(product_type=Concatted,
                                binary_type=ShellCatToOutFile,
                                input_selectors=(Select(Snapshot),),
                                input_conversion=file_list_to_args_for_cat_with_snapshot_subjects_and_output_file,
                                output_conversion=fail_process_result),
      SingletonRule(ShellCatToOutFile, ShellCatToOutFile()),
    ])

    request = scheduler.execution_request([Concatted],
                                          [PathGlobs.create('', include=['fs_test/a/b/*'])])
    root_entries = scheduler.execute(request).root_products

    self.assertEquals(1, len(root_entries))
    self.assertFirstEntryIsThrow(root_entries,
                                 in_msg='Failed in output conversion!')

  def assertFirstEntryIsReturn(self, root_entries, scheduler, execution_request):
    root, state = root_entries[0]
    self.assertReturn(state, scheduler, execution_request)
    return state

  def assertFirstEntryIsThrow(self, root_entries, in_msg=None):
    root, state = root_entries[0]
    self.assertIsInstance(state, Throw)
    if in_msg:
      self.assertIn(in_msg, str(state))
    return state

  def mk_example_fs_tree(self):
    fs_tree = self.mk_fs_tree(os.path.join(os.path.dirname(__file__), 'examples'))
    test_fs = os.path.join(fs_tree.build_root, 'fs_test')
    with tarfile.open(os.path.join(test_fs, 'fs_test.tar')) as tar:
      tar.extractall(test_fs)
    return fs_tree

  def mk_scheduler_in_example_fs(self, rules):
    rules = list(rules) + create_fs_rules() + create_process_rules()
    return self.mk_scheduler(rules=rules, project_tree=self.mk_example_fs_tree())

  def assertReturn(self, state, scheduler, execution_request):
    is_return = isinstance(state, Return)
    if is_return:
      return
    else:
      self.fail('Expected a Return, but found a {}. trace below:\n{}'
                .format(state, '\n'.join(scheduler.trace(execution_request))))

  def assertPathContains(self, expected_files, path):
    for i in expected_files:
      self.assertTrue(os.path.exists(os.path.join(path, i)),
                      'Expected {} to exist in {} but did not'.format(i, path))
