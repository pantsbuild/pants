# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest
from functools import partial

from pants.engine.engine import LocalSerialEngine
from pants.engine.fs import Files, PathGlobs
from pants.engine.isolated_process import (Binary, Checkout, ProcessExecutionNode, Snapshot,
                                           SnapshottedProcessRequest, SnapshottedProcessResult,
                                           SnapshottingRule)
from pants.engine.nodes import Return, StepContext
from pants.engine.scheduler import SnapshottedProcess
from pants.engine.selectors import Select, SelectLiteral
from pants.util.contextutil import open_tar
from pants.util.dirutil import safe_mkdir
from pants.util.objects import datatype
from pants_test.engine.scheduler_test_base import SchedulerTestBase


class FakeClassPath(object):
  pass


class GenericBinary(object):
  pass


class NothingInParticular(object):
  pass


def nothing_in_particular_to_request(args):
  pass


def request_to_fake_classpath(args):
  pass


class Concatted(datatype('Concatted', ['value'])):
  pass


class ShellCat(Binary):
  @property
  def bin_path(self):
    return '/bin/cat'


def file_list_to_args_for_cat(files):
  return SnapshottedProcessRequest(args=tuple(f.path for f in files.dependencies))


def file_list_to_args_for_cat_with_snapshot_subjects_and_output_file(files):
  return SnapshottedProcessRequest(args=tuple(f.path for f in files.dependencies),
                                   snapshot_subjects=[files])


def process_result_to_concatted_from_outfile(process_result, checkout):
  with open(os.path.join(checkout.path, 'outfile')) as f:
    # TODO might be better to allow for this to be done via Nodes. But I'm not sure how as yet.
    return Concatted(f.read())


def process_result_to_concatted(process_result, checkout):
  return Concatted(process_result.stdout)


def shell_cat_binary():
  return ShellCat()


def to_outfile_cat_binary():
  return ShellCatToOutFile()


class ShellCatToOutFile(Binary):
  def prefix_of_command(self):
    return tuple(['sh', '-c', 'cat $@ > outfile', 'unused'])

  @property
  def bin_path(self):
    return '/bin/cat'


class JavaOutputDir(datatype('JavaOutputDir', ['path'])):
  pass


class Javac(Binary):

  @property
  def bin_path(self):
    return '/usr/bin/javac'


def create_outdir(out_dir, checkout):
  safe_mkdir(os.path.join(checkout.path, out_dir.path))


def java_sources_to_javac_args(java_sources, out_dir):
  return SnapshottedProcessRequest(args=('-d', out_dir.path)+
                                        tuple(f.path for f in java_sources.dependencies),
                                   snapshot_subjects=[java_sources],
                                   prep_fn=partial(create_outdir, out_dir))


def javac_bin():
  return Javac()


class ClasspathEntry(datatype('ClasspathEntry', ['path'])):
  """A classpath entry for a subject."""


def process_result_to_classpath_entry(process_result, checkout):
  if not process_result.exit_code:
    # this implies that we should pass some / all of the inputs to the output conversion so they can grab config.
    # TODO string name association isn't great.
    return ClasspathEntry(os.path.join(checkout.path, 'build'))


class SnapshottedProcessRequestTest(SchedulerTestBase, unittest.TestCase):
  def test_converts_unhashable_args_to_tuples(self):
    request = SnapshottedProcessRequest(args=['1'], snapshot_subjects=[])

    self.assertIsInstance(request.args, tuple)
    self.assertIsInstance(request.snapshot_subjects, tuple)
    self.assertTrue(hash(request))


class IsolatedProcessTest(SchedulerTestBase, unittest.TestCase):

  def test_gather_snapshot_of_pathglobs(self):
    scheduler = self.mk_scheduler_in_example_fs([SnapshottingRule()])

    request = scheduler.execution_request([Snapshot],
                                          [PathGlobs.create('', rglobs=['fs_test/a/b/*'])])
    LocalSerialEngine(scheduler).reduce(request)

    root_entries = scheduler.root_entries(request).items()
    self.assertEquals(1, len(root_entries))
    state = self.assertFirstEntryIsReturn(root_entries, scheduler)
    snapshot = state.value

    with open_tar(snapshot.archive, errorlevel=1) as tar:
      self.assertEqual(['fs_test/a/b/1.txt', 'fs_test/a/b/2'],
                       [tar_info.path for tar_info in tar.getmembers()])

  def test_process_exec_node_directly(self):
    # process exec node needs to be able to do nailgun
    binary = ShellCat()  # Not 100% sure I like this here TODO make it better.
    process_request = SnapshottedProcessRequest(['fs_test/a/b/1.txt', 'fs_test/a/b/2'])
    project_tree = self.mk_example_fs_tree()

    context = StepContext(None, project_tree, tuple(), False)

    node = ProcessExecutionNode(binary, process_request, Checkout(project_tree.build_root))
    step_result = node.step(context)

    self.assertEqual(Return(SnapshottedProcessResult(stdout='one\ntwo\n', stderr='', exit_code=0)), step_result)

  def test_integration_simple_concat_test(self):
    scheduler = self.mk_scheduler_in_example_fs(
      [SnapshottedProcess(product_type=Concatted, binary_type=ShellCat,
                          input_selectors=(Select(Files),),
                          input_conversion=file_list_to_args_for_cat,
                          output_conversion=process_result_to_concatted),
       [ShellCat, [], shell_cat_binary]])

    request = scheduler.execution_request([Concatted],
                                          [PathGlobs.create('', rglobs=['fs_test/a/b/*'])])
    LocalSerialEngine(scheduler).reduce(request)

    root_entries = scheduler.root_entries(request).items()
    self.assertEquals(1, len(root_entries))
    state = self.assertFirstEntryIsReturn(root_entries, scheduler)
    concatted = state.value

    self.assertEqual(Concatted('one\ntwo\n'), concatted)

  def test_integration_concat_with_snapshot_subjects_test(self):
    scheduler = self.mk_scheduler_in_example_fs([
      SnapshottingRule(),
      # subject to files / product of subject to files for snapshot.
      SnapshottedProcess(product_type=Concatted,
                         binary_type=ShellCatToOutFile,
                         input_selectors=(Select(Files),),
                         input_conversion=file_list_to_args_for_cat_with_snapshot_subjects_and_output_file,
                         output_conversion=process_result_to_concatted_from_outfile),
      [ShellCatToOutFile, [], to_outfile_cat_binary]
    ])

    request = scheduler.execution_request([Concatted],
                                          [PathGlobs.create('', rglobs=['fs_test/a/b/*'])])
    LocalSerialEngine(scheduler).reduce(request)

    root_entries = scheduler.root_entries(request).items()
    self.assertEquals(1, len(root_entries))
    state = self.assertFirstEntryIsReturn(root_entries, scheduler)
    concatted = state.value

    self.assertEqual(Concatted('one\ntwo\n'), concatted)

  def test_javac_compilation_example(self):
    sources = PathGlobs.create('', files=['scheduler_inputs/src/java/simple/Simple.java'])

    scheduler = self.mk_scheduler_in_example_fs([
      SnapshottingRule(),
      SnapshottedProcess(ClasspathEntry,
                         Javac,
                         (Select(Files), SelectLiteral(JavaOutputDir('build'), JavaOutputDir)),
                         java_sources_to_javac_args,
                         process_result_to_classpath_entry),
      [Javac, [], javac_bin]
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

  def assertFirstEntryIsReturn(self, root_entries, scheduler):
    root, state = root_entries[0]
    self.assertReturn(state, root, scheduler)
    return state

  def mk_example_fs_tree(self):
    return self.mk_fs_tree(os.path.join(os.path.dirname(__file__), 'examples'))

  def mk_scheduler_in_example_fs(self, rules):
    project_tree = self.mk_example_fs_tree()
    scheduler = self.mk_scheduler(tasks=rules,
                                  project_tree=project_tree)
    return scheduler

  def assertReturn(self, state, root, scheduler):
    is_return = isinstance(state, Return)
    if is_return:
      return
    else:
      self.fail('Expected a Return, but found a {}. trace below:\n{}'
                .format(state, '\n'.join(scheduler.product_graph.trace(root))))

  def assertPathContains(self, expected_files, path):
    for i in expected_files:
      self.assertTrue(os.path.exists(os.path.join(path, i)),
                      'Expected {} to exist in {} but did not'.format(i, path))
