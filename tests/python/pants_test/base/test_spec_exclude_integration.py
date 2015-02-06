# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess
import tempfile
from contextlib import contextmanager
from shutil import rmtree

from pants.base.build_environment import get_buildroot
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class Bundles(object):
  """Container class to hold test bundle specifications."""

  phrase_path = 'testprojects/src/java/com/pants/testproject/phrases'

  class Bundle(object):
    def __init__(self, spec, text):
      self.spec = spec
      self.text = text

    def __hash__(self):
      return hash((self.spec, self.text))

    @property
    def full_spec(self):
      return '{project}:{name}'.format(project=Bundles.phrase_path, name=self.spec)

  # Bundles and their magic strings to expect in run outputs.
  lesser_of_two = Bundle('lesser-of-two',
      "One must choose the lesser of two eval()s.")
  once_upon_a_time = Bundle('once-upon-a-time',
      "Once upon a time, in a far away land, there were some pants.")
  ten_thousand = Bundle('ten-thousand',
      "And now you must face my army of ten thousand BUILD files.")
  there_was_a_duck = Bundle('there-was-a-duck',
      "And also, there was a duck.")

  all_bundles = [lesser_of_two, once_upon_a_time, ten_thousand, there_was_a_duck,]


class SpecExcludeIntegrationTest(PantsRunIntegrationTest):
  """Tests the functionality of the --spec-exclude flag in pants."""

  def _bundle_path(self, bundle):
    return os.path.join(get_buildroot(), 'dist', '{name}-bundle'.format(name=bundle))

  @contextmanager
  def _handle_bundles(self, names):
    """Makes sure bundles don't exist to begin with, and deletes them afterward."""
    paths = [self._bundle_path(name) for name in names]
    jars = ['{name}.jar'.format(name=name) for name in names]
    yield (paths, jars)
    missing = []
    for path in paths:
      if os.path.exists(path):
        rmtree(path)
      else:
        missing.append(path)
    self.assertFalse(missing, "Some bundles weren't generated! {missing}"
        .format(missing=', '.join(missing)))

  def _test_bundle_existences(self, args, bundles, config=None):
    all_bundles = set(bundle.spec for bundle in Bundles.all_bundles)
    all_paths = [self._bundle_path(bundle) for bundle in all_bundles]

    names = [bundle.spec for bundle in bundles]
    outputs = [bundle.text for bundle in bundles]

    for path in all_paths:
      if os.path.exists(path):
        rmtree(path)

    with self._handle_bundles(names) as (paths, jars):
      pants_run = self.run_pants(['bundle'] + args, config=config)
      self.assert_success(pants_run)
      for path, jar, expected in zip(paths, jars, outputs):
        java_run = subprocess.Popen(['java', '-jar', jar],
                                    stdout=subprocess.PIPE,
                                    cwd=path)
        java_retcode = java_run.wait()
        java_out = java_run.stdout.read()
        self.assertEquals(java_retcode, 0)
        self.assertTrue(expected in java_out, "Expected '{output}' from {jar}, not '{stdout}'."
                                              .format(output=expected, jar=jar, stdout=java_out))

    lingering = [path for path in all_paths if os.path.exists(path)]
    self.assertTrue(not lingering, "Left with unexpected bundles! {bundles}"
                                   .format(bundles=', '.join(lingering)))

  def test_single_run(self):
    """Test whether we can run a single target without special flags."""
    self._test_bundle_existences(
        [Bundles.lesser_of_two.full_spec,],
        [Bundles.lesser_of_two,],
    )

  def test_double_run(self):
    """Test whether we can run two targets without special flags."""
    self._test_bundle_existences(
        [Bundles.lesser_of_two.full_spec, Bundles.once_upon_a_time.full_spec,],
        [Bundles.lesser_of_two, Bundles.once_upon_a_time,],
    )

  def test_all_run(self):
    """Test whether we can run everything with ::."""
    self._test_bundle_existences(
        [Bundles.phrase_path + '::',],
        Bundles.all_bundles,
    )

  def test_exclude_lesser(self):
    self._test_bundle_existences(
        [Bundles.phrase_path + '::', '--exclude-target-regexp=lesser',],
        set(Bundles.all_bundles) - set([Bundles.lesser_of_two,]),
    )

  def test_exclude_thoe(self):
    self._test_bundle_existences(
        [Bundles.phrase_path + '::', r'--exclude-target-regexp=\bth[oe]',],
        set(Bundles.all_bundles) - set([Bundles.there_was_a_duck, Bundles.ten_thousand,]),
    )

  def test_exclude_two(self):
    self._test_bundle_existences([
          Bundles.phrase_path + '::',
          '--exclude-target-regexp=duck',
          '--exclude-target-regexp=time',
        ],
        set(Bundles.all_bundles) - set([Bundles.there_was_a_duck, Bundles.once_upon_a_time,]),
    )


class SpecExcludePantsIniIntegrationTest(PantsRunIntegrationTest):
  """Tests the functionality of the exclude_specs option in pants.ini ."""

  def test_exclude_spec_pants_ini(self):
    def output_to_list(output_filename):
      with open(output_filename, 'r') as results_file:
        return set([line.rstrip() for line in results_file.readlines()])

    tempdir = tempfile.mkdtemp()
    tmp_output = os.path.join(tempdir, 'minimize-output1.txt')
    run_result = self.run_pants(['minimize',
                                 'testprojects::',
                                 '--quiet',
                                 '--minimize-output-file={0}'.format(tmp_output)])
    self.assert_success(run_result)
    results = output_to_list(tmp_output)
    self.assertIn('testprojects/src/java/com/pants/testproject/phrases:ten-thousand',
                  results)
    self.assertIn('testprojects/src/java/com/pants/testproject/phrases:once-upon-a-time',
                  results)
    self.assertIn('testprojects/src/java/com/pants/testproject/phrases:lesser-of-two',
                  results)
    self.assertIn('testprojects/src/java/com/pants/testproject/phrases:there-was-a-duck',
                  results)

    tmp_output = os.path.join(tempdir, 'minimize-output2.txt')

    run_result = self.run_pants(['minimize',
                                 'testprojects::',
                                 '--quiet',
                                 '--minimize-output-file={0}'.format(tmp_output)],
                                config={
                                    'DEFAULT': {
                                        'spec_excludes': [
                                            'testprojects/src/java/com/pants/testproject/phrases'
                                        ]
                                    }
                                })
    self.assert_success(run_result)
    results = output_to_list(tmp_output)
    self.assertNotIn('testprojects/src/java/com/pants/testproject/phrases:ten-thousand',
                     results)
    self.assertNotIn('testprojects/src/java/com/pants/testproject/phrases:once-upon-a-time',
                     results)
    self.assertNotIn('testprojects/src/java/com/pants/testproject/phrases:lesser-of-two',
                     results)
    self.assertNotIn('testprojects/src/java/com/pants/testproject/phrases:there-was-a-duck',
                     results)
