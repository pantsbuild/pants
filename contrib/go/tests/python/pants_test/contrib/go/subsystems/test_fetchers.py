# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.subsystem.util import global_subsystem_instance
from pants.testutil.test_base import TestBase

from pants.contrib.go.subsystems.fetcher_factory import FetcherFactory


class FetchersTest(TestBase):
    def fetcher(self, import_path):
        fetcher_factory = global_subsystem_instance(FetcherFactory)
        return fetcher_factory.get_fetcher(import_path)

    def check_default(self, import_path, expected_root):
        fetcher = self.fetcher(import_path)
        self.assertEqual(expected_root, fetcher.root())

    def test_default_bitbucket(self):
        self.check_default(
            "bitbucket.org/rj/sqlite3-go", expected_root="bitbucket.org/rj/sqlite3-go"
        )
        self.check_default(
            "bitbucket.org/neuronicnobody/go-opencv/opencv",
            expected_root="bitbucket.org/neuronicnobody/go-opencv",
        )

    def test_default_github(self):
        self.check_default(
            "github.com/bitly/go-simplejson", expected_root="github.com/bitly/go-simplejson"
        )
        self.check_default(
            "github.com/docker/docker/daemon/events", expected_root="github.com/docker/docker"
        )

    def test_default_golang(self):
        self.check_default("golang.org/x/oauth2", expected_root="golang.org/x/oauth2")
        self.check_default("golang.org/x/net/context", expected_root="golang.org/x/net")

    def test_default_gopkg(self):
        self.check_default("gopkg.in/check.v1", expected_root="gopkg.in/check.v1")
