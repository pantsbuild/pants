# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest
from contextlib import contextmanager

import mock
import requests
from pants.util.contextutil import temporary_dir
from pants_test.subsystem.subsystem_util import subsystem_instance

from pants.contrib.go.subsystems.fetchers import ArchiveFetcher, Fetchers, GopkgInFetcher


class FetchersTest(unittest.TestCase):
  # TODO(John Sirois): Add more tests of the Fetches subsystem: advertisement and aliasing as part
  # of: https://github.com/pantsbuild/pants/issues/2018

  @contextmanager
  def fetcher(self, import_path):
    with subsystem_instance(Fetchers) as fetchers:
      yield fetchers.get_fetcher(import_path)

  def check_unmapped(self, import_path):
    with self.assertRaises(Fetchers.UnfetchableRemote):
      with self.fetcher(import_path):
        self.fail('Expected get_fetcher to raise.')

  def test_default_unmapped(self):
    self.check_unmapped('')
    self.check_unmapped('https://github.com')
    self.check_unmapped('api.github.com')

  def check_default(self, import_path, expected_root):
    with self.fetcher(import_path) as fetcher:
      self.assertEqual(expected_root, fetcher.root(import_path))

  def test_default_bitbucket(self):
    self.check_default('bitbucket.org/rj/sqlite3-go',
                       expected_root='bitbucket.org/rj/sqlite3-go')
    self.check_default('bitbucket.org/neuronicnobody/go-opencv/opencv',
                       expected_root='bitbucket.org/neuronicnobody/go-opencv')

  def test_default_github(self):
    self.check_default('github.com/bitly/go-simplejson',
                       expected_root='github.com/bitly/go-simplejson')
    self.check_default('github.com/docker/docker/daemon/events',
                       expected_root='github.com/docker/docker')

  def test_default_golang(self):
    self.check_default('golang.org/x/oauth2',
                       expected_root='golang.org/x/oauth2')
    self.check_default('golang.org/x/net/context',
                       expected_root='golang.org/x/net')

  def test_default_gopkg(self):
    self.check_default('gopkg.in/check.v1', expected_root='gopkg.in/check.v1')


class GolangOrgFetcherTest(unittest.TestCase):

  def do_fetch(self, import_path, expected_url, rev=None):
    with subsystem_instance(ArchiveFetcher) as fetcher:
      fetcher._fetch = mock.MagicMock(spec=fetcher._fetch)
      with temporary_dir() as dest:
        fetcher.fetch(import_path, dest, rev=rev)

      # For some reason using `assert_called_once_with` like so:
      #   fetcher._fetch.assert_called_once_with(expected_url)
      #
      # Yields this error:
      # E       AssertionError:
      #           Expected call: mock(u'https://github.com/golang/oauth2/archive/master.tar.gz')
      # E       Actual call: mock(u'https://github.com/golang/oauth2/archive/master.tar.gz')
      # E       too many positional arguments
      #
      # So we manually check called once with in 2 steps.
      self.assertEqual(1, fetcher._fetch.call_count)
      self.assertEqual(mock.call(expected_url), fetcher._fetch.call_args)

  def test_fetch(self):
    self.do_fetch(import_path='golang.org/x/oauth2',
                  expected_url='https://github.com/golang/oauth2/archive/master.tar.gz')
    self.do_fetch(import_path='golang.org/x/net/context',
                  expected_url='https://github.com/golang/net/archive/master.tar.gz')

  def test_fetch_rev(self):
    self.do_fetch(import_path='golang.org/x/oauth2',
                  rev='abc123',
                  expected_url='https://github.com/golang/oauth2/archive/abc123.tar.gz')
    self.do_fetch(import_path='golang.org/x/net/context',
                  rev='def456',
                  expected_url='https://github.com/golang/net/archive/def456.tar.gz')


class GopkgInFetcherTest(unittest.TestCase):
  def test_root_bad_domain(self):
    with subsystem_instance(GopkgInFetcher) as fetcher:
      with self.assertRaises(fetcher.FetchError):
        fetcher.root('gopkg.com/check.v1')

  def test_root_pkg_simple(self):
    with subsystem_instance(GopkgInFetcher) as fetcher:
      root = fetcher.root('gopkg.in/check.v1')
      self.assertEqual('gopkg.in/check.v1', root)

  def test_root_pkg_subpackage(self):
    with subsystem_instance(GopkgInFetcher) as fetcher:
      root = fetcher.root('gopkg.in/amz.v1/s3')
      self.assertEqual('gopkg.in/amz.v1', root)

  def test_root_user_pkg_simple(self):
    with subsystem_instance(GopkgInFetcher) as fetcher:
      root = fetcher.root('gopkg.in/bob/check.v1')
      self.assertEqual('gopkg.in/bob/check.v1', root)

  def test_root_user_pkg_subpackage(self):
    with subsystem_instance(GopkgInFetcher) as fetcher:
      root = fetcher.root('gopkg.in/bob/amz.v1/s3')
      self.assertEqual('gopkg.in/bob/amz.v1', root)

  def do_fetch(self, import_path, version_override=None, github_api_responses=None,
               expected_fetch=None):
    # Simulate a series of github api calls to list refs for the given import paths.
    # Optionally asserts an expected fetch call to the underlying fetcher.
    with subsystem_instance(GopkgInFetcher) as fetcher:
      fetcher._do_get = mock.Mock(spec=fetcher._do_get)
      fetcher._do_get.side_effect = github_api_responses
      fetcher._do_fetch = mock.Mock(spec=fetcher._do_fetch)
      with temporary_dir() as dest:
        fetcher.fetch(import_path, dest, rev=version_override)
      if expected_fetch:
        expected_url, expected_rev = expected_fetch
        fetcher._do_fetch.assert_called_once_with(expected_url, dest, expected_rev)

  def test_no_tags_or_branches(self):
    with self.assertRaises(GopkgInFetcher.NoVersionsError):
      self.do_fetch('gopkg.in/check.v1', github_api_responses=([], []))

  def test_invalid_tags_or_branches(self):
    with self.assertRaises(GopkgInFetcher.NoMatchingVersionError):
      self.do_fetch('gopkg.in/check.v1', github_api_responses=([{'ref': 'refs/tags/v1BAD'},
                                                                {'ref': 'refs/tags/v1.BAD'}],
                                                               [{'ref': 'refs/heads/v1WORSE'},
                                                                {'ref': 'refs/heads/v1.WORSE'},
                                                                {'ref': 'refs/heads/v1.W.O.R'},
                                                                {'ref': 'refs/heads/v1.W.2'}]))

  def test_no_tags_or_branches_one_error(self):
    with self.assertRaises(GopkgInFetcher.FetchError):
      self.do_fetch('gopkg.in/check.v1', github_api_responses=([], requests.RequestException()))

    with self.assertRaises(GopkgInFetcher.FetchError):
      self.do_fetch('gopkg.in/check.v1', github_api_responses=(requests.RequestException(), []))

  def test_no_tags_or_branches_two_errors(self):
    with self.assertRaises(GopkgInFetcher.ApiError):
      self.do_fetch('gopkg.in/check.v1', github_api_responses=(requests.RequestException(),
                                                               requests.RequestException()))

  def test_tag_match_exact(self):
    self.do_fetch('gopkg.in/check.v1',
                  github_api_responses=([{'ref': 'refs/tags/v1'}], []),
                  expected_fetch=('github.com/go-check/check', 'v1'))

  def test_tag_match_exact_subpackage(self):
    self.do_fetch('gopkg.in/check.v1/sub/pkg',
                  github_api_responses=([{'ref': 'refs/tags/v1'}], []),
                  expected_fetch=('github.com/go-check/check', 'v1'))

  def test_user_protocol(self):
    self.do_fetch('gopkg.in/fred/bob.v5',
                  github_api_responses=([{'ref': 'refs/tags/v5.5'}], []),
                  expected_fetch=('github.com/fred/bob', 'v5.5'))

  def test_user_protocol_subpackage(self):
    self.do_fetch('gopkg.in/fred/bob.v5/sub/pkg',
                  github_api_responses=([{'ref': 'refs/tags/v5.5'}], []),
                  expected_fetch=('github.com/fred/bob', 'v5.5'))

  def test_version_override(self):
    no_api_call = AssertionError('Expected no github API calls with a version override from the '
                                 'BUILD file.')
    self.do_fetch('gopkg.in/fred/bob.v5',
                  version_override='17cd821d58c93fa395c239dfbd8e12a42c17b743',
                  github_api_responses=(no_api_call, no_api_call),
                  expected_fetch=('github.com/fred/bob',
                                  '17cd821d58c93fa395c239dfbd8e12a42c17b743'))

  def test_tag_match_major_beats_minor(self):
    self.do_fetch('gopkg.in/check.v1',
                  github_api_responses=([{'ref': 'refs/tags/v1'},
                                         {'ref': 'refs/tags/v1.1'},
                                         {'ref': 'refs/tags/v1.0.1'}],
                                        []),
                  expected_fetch=('github.com/go-check/check', 'v1.1'))

  def test_tag_match_short_circuits(self):
    no_branches_call = AssertionError('Expected tag match to short circuit branches api call')
    self.do_fetch('gopkg.in/check.v1',
                  github_api_responses=([{'ref': 'refs/tags/v1.5'}], no_branches_call))

  def test_branch_match_exact(self):
    self.do_fetch('gopkg.in/check.v1', github_api_responses=([], [{'ref': 'refs/heads/v1'}]))

  def test_branch_match_major_beats_minor(self):
    self.do_fetch('gopkg.in/check.v1',
                  github_api_responses=([],
                                        [{'ref': 'refs/heads/v1'},
                                         {'ref': 'refs/heads/v1.1'},
                                         {'ref': 'refs/heads/v1.0.1'}]),
                  expected_fetch=('github.com/go-check/check', 'v1.1'))

  def test_branch_match_fall_through(self):
    self.do_fetch('gopkg.in/check.v1',
                  github_api_responses=([{'ref': 'refs/tags/v2'}],  # non-matching tag
                                        [{'ref': 'refs/heads/v1.2.3'}]),
                  expected_fetch=('github.com/go-check/check', 'v1.2.3'))

  def test_v0_tag_match(self):
    # This emulates a real case discovered here: https://github.com/pantsbuild/pants/issues/2233
    self.do_fetch('gopkg.in/fsnotify.v0',
                  github_api_responses=([{'ref': 'refs/tags/v0.8.06'},
                                         {'ref': 'refs/tags/v0.8.07'},
                                         {'ref': 'refs/tags/v0.8.08'},
                                         {'ref': 'refs/tags/v0.8.09'},
                                         {'ref': 'refs/tags/v0.8.10'},
                                         {'ref': 'refs/tags/v0.8.11'},
                                         {'ref': 'refs/tags/v0.8.12'},
                                         {'ref': 'refs/tags/v0.8.13'},
                                         {'ref': 'refs/tags/v0.9.0'},
                                         {'ref': 'refs/tags/v0.9.1'},
                                         {'ref': 'refs/tags/v0.9.2'},
                                         {'ref': 'refs/tags/v0.9.3'},
                                         {'ref': 'refs/tags/v1.0.0'}],
                                        [{'ref': 'refs/heads/master'},
                                         {'ref': 'refs/heads/v0'}]),
                  expected_fetch=('github.com/go-fsnotify/fsnotify', 'v0.9.3'))

  def test_v0_no_matches(self):
    self.do_fetch('gopkg.in/fsnotify.v0',
                  github_api_responses=([{'ref': 'refs/tags/v1.0.0'}],
                                        []),
                  expected_fetch=('github.com/go-fsnotify/fsnotify', 'master'))
