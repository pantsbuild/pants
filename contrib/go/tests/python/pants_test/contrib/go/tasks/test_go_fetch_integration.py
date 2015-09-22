# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class GoFetchIntegrationTest(PantsRunIntegrationTest):

  def test_go_fetch_integration(self):
    args = ['run',
            'contrib/go/examples/src/go/server']
    pants_run = self.run_pants(args)
    self.assert_success(pants_run)

  def test_issues_1998(self):
    # Only the 3 explicit targets below are defined on disk, the 2 implicit AdRoll/goamz targets
    # are created on the fly at the same rev as the explicit github.com/AdRoll/goamz:dynamodb and
    # they're hydrated from the same downloaded tarball.
    #
    # github.com/AdRoll/goamz:dynamodb
    # -> github.com/AdRoll/goamz/aws (implicit)
    # -> github.com/AdRoll/goamz:dynamodb/dynamizer (implicit)
    #    -> github.com/cbroglie/mapstructure
    # -> github.com/bitly/go-simplejson
    args = ['compile',
            'contrib/go/examples/3rdparty/go/github.com/AdRoll/goamz:dynamodb']
    pants_run = self.run_pants(args)
    self.assert_success(pants_run)

  def test_issues_2004(self):
    # The target used here has test imports outside those used by the source code it tests (that
    # code only depends on the stdlib).  These must be resolved for the test to be compiled and run:
    #
    # github.com/bitly/go-simplejson
    # -> github.com/bmizerany/assert (testing)
    #    -> github.com/kr/pretty (testing)
    #       -> github.com/kr/text (testing)
    args = ['test.go',
            '--remote',
            'contrib/go/examples/3rdparty/go/github.com/bitly/go-simplejson']
    pants_run = self.run_pants(args)
    self.assert_success(pants_run)

  def test_issues_2229(self):
    # The target used here has tests that use relative imports.  In order to resolve the target
    # and compile it, pants must be able to handle the relative imports.
    args = ['compile',
            'contrib/go/examples/3rdparty/go/github.com/robertkrimen/otto']
    pants_run = self.run_pants(args)
    self.assert_success(pants_run)
