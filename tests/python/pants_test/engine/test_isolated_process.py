# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import tarfile
import unittest

from pants.engine.engine import LocalSerialEngine
from pants.engine.fs import PathGlobs, Snapshot
from pants.engine.isolated_process import Binary, SnapshottedProcess, SnapshottedProcessRequest
from pants.engine.nodes import Return, Throw
from pants.engine.rules import SingletonRule
from pants.engine.selectors import Select
from pants.util.objects import datatype
from pants_test.engine.scheduler_test_base import SchedulerTestBase


class Concatted(datatype('Concatted', ['value'])):
  pass


class ShellCat(Binary):
  @property
  def bin_path(self):
    return '/bin/cat'


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
  def prefix_of_command(self):
    return tuple(['sh', '-c', 'cat $@ > outfile', 'unused'])


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


class ClasspathEntry(datatype('ClasspathEntry', ['path'])):
  """A classpath entry for a subject."""


def process_result_to_classpath_entry(process_result, sandbox_dir):
  if not process_result.exit_code:
    # this implies that we should pass some / all of the inputs to the output conversion so they can grab config.
    # TODO string name association isn't great.
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
    LocalSerialEngine(scheduler).reduce(request)

    root_entries = scheduler.root_entries(request).items()
    self.assertEquals(1, len(root_entries))
    state = self.assertFirstEntryIsReturn(root_entries, scheduler)
    concatted = state.value

    self.assertEqual(Concatted('one\ntwo\n'), concatted)

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
    LocalSerialEngine(scheduler).reduce(request)

    root_entries = scheduler.root_entries(request).items()
    self.assertEquals(1, len(root_entries))
    state = self.assertFirstEntryIsReturn(root_entries, scheduler)
    classpath_entry = state.value
    self.assertIsInstance(classpath_entry, ClasspathEntry)
    self.assertTrue(os.path.exists(os.path.join(classpath_entry.path, 'simple', 'Simple.class')))

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
    LocalSerialEngine(scheduler).reduce(request)

    root_entries = scheduler.root_entries(request).items()
    self.assertEquals(1, len(root_entries))
    self.assertFirstEntryIsThrow(root_entries,
                                 in_msg='Running ShellFailCommand failed with non-zero exit code: 1')

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
    LocalSerialEngine(scheduler).reduce(request)

    root_entries = scheduler.root_entries(request).items()
    self.assertEquals(1, len(root_entries))
    self.assertFirstEntryIsThrow(root_entries,
                                 in_msg='Failed in output conversion!')

  def assertFirstEntryIsReturn(self, root_entries, scheduler):
    root, state = root_entries[0]
    self.assertReturn(state, scheduler)
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
    return self.mk_scheduler(tasks=rules, project_tree=self.mk_example_fs_tree())

  def assertReturn(self, state, scheduler):
    is_return = isinstance(state, Return)
    if is_return:
      return
    else:
      self.fail('Expected a Return, but found a {}. trace below:\n{}'
                .format(state, '\n'.join(scheduler.trace())))

  def assertPathContains(self, expected_files, path):
    for i in expected_files:
      self.assertTrue(os.path.exists(os.path.join(path, i)),
                      'Expected {} to exist in {} but did not'.format(i, path))
