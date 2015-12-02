# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

import mock

from pants.task.scm_publish_mixin import ScmPublishMixin


class ScmPublishMixinTest(unittest.TestCase):
  class ScmPublish(ScmPublishMixin):
    def __init__(self, restrict_push_branches=None, restrict_push_urls=None):
      self._restrict_push_branches = restrict_push_branches
      self._restrict_push_urls = restrict_push_urls
      self._scm = mock.Mock()
      self._log = mock.MagicMock()

    @property
    def restrict_push_branches(self):
      return self._restrict_push_branches

    @property
    def restrict_push_urls(self):
      return self._restrict_push_urls

    @property
    def scm_push_attempts(self):
      raise NotImplementedError()

    @property
    def scm(self):
      return self._scm

    @property
    def log(self):
      return self._log

  def test_check_clean_master_dry_run_bad_branch(self):
    scm_publish = self.ScmPublish(restrict_push_branches=['bob'])
    scm_publish.scm.branch_name = 'jane'
    scm_publish.check_clean_master(commit=False)

  def test_check_clean_master_dry_run_bad_remote(self):
    scm_publish = self.ScmPublish(restrict_push_urls=['amy'])
    # Property mocks must be installed on the type instead of on the instance, see:
    #   http://www.voidspace.org.uk/python/mock/mock.html#mock.PropertyMock
    type(scm_publish.scm).server_url = mock.PropertyMock(side_effect=AssertionError)
    scm_publish.check_clean_master(commit=False)

  def test_check_clean_master_dry_run_unclean(self):
    scm_publish = self.ScmPublish()
    scm_publish.scm.changed_files.side_effect = AssertionError
    scm_publish.check_clean_master(commit=False)

  def test_check_clean_master_success_acceptable_branch(self):
    scm_publish = self.ScmPublish(restrict_push_branches=['bob', 'betty'])
    scm_publish.scm.branch_name = 'betty'
    scm_publish.scm.changed_files.return_value = []
    scm_publish.check_clean_master(commit=True)

  def test_check_clean_master_success_acceptable_remote(self):
    scm_publish = self.ScmPublish(restrict_push_urls=['amy', 'fred'])
    scm_publish.scm.server_url = 'fred'
    scm_publish.scm.changed_files.return_value = []
    scm_publish.check_clean_master(commit=True)

  def test_check_clean_master_bad_branch(self):
    scm_publish = self.ScmPublish(restrict_push_branches=['bob'])
    scm_publish.scm.branch_name = 'jane'
    with self.assertRaises(scm_publish.InvalidBranchError):
      scm_publish.check_clean_master(commit=True)

  def test_check_clean_master_bad_remote(self):
    scm_publish = self.ScmPublish(restrict_push_urls=['amy'])
    scm_publish.scm.serveer_url = 'https://amy'
    with self.assertRaises(scm_publish.InvalidRemoteError):
      scm_publish.check_clean_master(commit=True)

  def test_check_clean_master_dirty(self):
    scm_publish = self.ScmPublish()
    scm_publish.scm.changed_files.return_value = ['dirty/file']
    with self.assertRaises(scm_publish.DirtyWorkspaceError):
      scm_publish.check_clean_master(commit=True)
