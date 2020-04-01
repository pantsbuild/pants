# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest
from unittest.mock import Mock

from pants.backend.jvm.artifact import Artifact
from pants.backend.jvm.repository import Repository
from pants.backend.jvm.scala_artifact import ScalaArtifact
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.jar_publish import JarPublish
from pants.base.exceptions import TaskError
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.target import Target
from pants.scm.scm import Scm
from pants.testutil.jvm.nailgun_task_test_base import NailgunTaskTestBase
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir, safe_mkdtemp, safe_walk
from pants.util.memo import memoized_classproperty


class JarPublishTest(NailgunTaskTestBase):
    @classmethod
    def task_type(cls):
        return JarPublish

    def test_smoke_publish(self):
        with temporary_dir() as publish_dir:
            self.set_options(local=publish_dir)
            task = self.create_task(self.context())
            task.execute()

    @classmethod
    def alias_groups(cls):
        return BuildFileAliases(
            targets={"jar_library": JarLibrary, "java_library": JavaLibrary, "target": Target},
            objects={"artifact": Artifact, "scala_artifact": ScalaArtifact},
            context_aware_object_factories={
                "internal": lambda _: Repository(
                    name="internal", url="http://example.com", push_db_basedir=cls.push_db_basedir
                ),
            },
        )

    @memoized_classproperty
    def push_db_basedir(cls):
        return safe_mkdtemp()

    def setUp(self):
        super().setUp()
        safe_mkdir(self.push_db_basedir, clean=True)

    def _prepare_for_publishing(self, with_alias=False):
        targets = []
        nail_target = self._create_nail_target()
        targets.append(nail_target)

        shoe_target = self.create_library(
            path="b",
            target_type="java_library",
            name="b",
            sources=["B.java"],
            provides="artifact(org='com.example', name='shoe', repo=internal)",
            dependencies=[nail_target.address.reference()],
        )
        targets.append(shoe_target)

        shoe_address = shoe_target.address.reference()
        if with_alias:
            # add an alias target between c and b
            alias_target = self.create_library(
                path="z", target_type="target", name="z", dependencies=[shoe_address]
            )
            targets.append(alias_target)
            horse_deps = [alias_target.address.reference()]
        else:
            horse_deps = [shoe_address]

        horse_target = self.create_library(
            path="c",
            target_type="java_library",
            name="c",
            sources=["C.java"],
            provides="artifact(org='com.example', name='horse', repo=internal)",
            dependencies=horse_deps,
        )
        targets.append(horse_target)
        return targets

    def _create_nail_target(self):
        return self.create_library(
            path="a",
            target_type="java_library",
            name="a",
            sources=["A.java"],
            provides="artifact(org='com.example', name='nail', repo=internal)",
        )

    def _prepare_targets_with_duplicates(self):
        targets = list(self._prepare_for_publishing())
        conflict = self.create_library(
            path="conflict",
            target_type="java_library",
            name="conflict",
            sources=["Conflict.java"],
            provides="artifact(org='com.example', name='nail', repo=internal)",
        )
        targets.append(conflict)
        return targets

    def _get_repos(self):
        return {"internal": {"resolver": "example.com"}}

    def _prepare_mocks(self, task):
        task.scm = Mock()
        task.scm.changed_files = Mock(return_value=[])
        task._copy_artifact = Mock()
        task.create_source_jar = Mock()
        task.create_doc_jar = Mock()
        task.changelog = Mock(return_value="Many changes")
        task.publish = Mock()
        task.confirm_push = Mock(return_value=True)
        task.context.products.get = Mock(return_value=Mock())

    def test_publish_unlisted_repo(self):
        # Note that we set a different config here, so repos:internal has no config
        repos = {"another-repo": {"resolver": "example.org"}}

        targets = self._prepare_for_publishing()
        with temporary_dir():
            self.set_options(dryrun=False, repos=repos)
            task = self.create_task(self.context(target_roots=targets))
            self._prepare_mocks(task)
            with self.assertRaises(TaskError):
                try:
                    task.execute()
                except TaskError as e:
                    assert "Repository internal has no" in str(e)
                    raise e

    def test_publish_local_dryrun(self):
        targets = self._prepare_for_publishing()

        with temporary_dir() as publish_dir:
            self.set_options(local=publish_dir)
            task = self.create_task(self.context(target_roots=targets))
            self._prepare_mocks(task)
            task.execute()

            # Nothing is written to the pushdb during a dryrun publish
            # (maybe some directories are created, but git will ignore them)
            files = []
            for _, _, filenames in safe_walk(self.push_db_basedir):
                files.extend(filenames)
            self.assertEqual(
                0, len(files), "Nothing should be written to the pushdb during a dryrun publish"
            )

            self.assertEqual(
                0, task.confirm_push.call_count, "Expected confirm_push not to be called"
            )
            self.assertEqual(0, task.publish.call_count, "Expected publish not to be called")

    def test_publish_local(self):
        for with_alias in [True, False]:
            targets = self._prepare_for_publishing(with_alias=with_alias)

            with temporary_dir() as publish_dir:
                self.set_options(dryrun=False, local=publish_dir)
                task = self.create_task(self.context(target_roots=targets))
                self._prepare_mocks(task)
                task.execute()

                # Nothing is written to the pushdb during a local publish
                # (maybe some directories are created, but git will ignore them)
                files = []
                for _, _, filenames in safe_walk(self.push_db_basedir):
                    files.extend(filenames)
                self.assertEqual(
                    0, len(files), "Nothing should be written to the pushdb during a local publish"
                )

                publishable_count = len(targets) - (1 if with_alias else 0)
                self.assertEqual(
                    publishable_count,
                    task.confirm_push.call_count,
                    "Expected one call to confirm_push per artifact",
                )
                self.assertEqual(
                    publishable_count,
                    task.publish.call_count,
                    "Expected one call to publish per artifact",
                )

    def test_publish_remote(self):
        targets = self._prepare_for_publishing()
        self.set_options(dryrun=False, repos=self._get_repos(), push_postscript="\nPS")
        task = self.create_task(self.context(target_roots=targets))
        self._prepare_mocks(task)
        task.execute()

        # One file per task is written to the pushdb during a local publish
        files = []
        for _, _, filenames in safe_walk(self.push_db_basedir):
            files.extend(filenames)

        self.assertEqual(
            len(targets),
            len(files),
            "During a remote publish, one pushdb should be written per target",
        )
        self.assertEqual(
            len(targets),
            task.confirm_push.call_count,
            "Expected one call to confirm_push per artifact",
        )
        self.assertEqual(
            len(targets), task.publish.call_count, "Expected one call to publish per artifact"
        )

        self.assertEqual(
            len(targets), task.scm.commit.call_count, "Expected one call to scm.commit per artifact"
        )
        args, kwargs = task.scm.commit.call_args
        message = args[0]
        message_lines = message.splitlines()
        self.assertTrue(
            len(message_lines) > 1,
            "Expected at least one commit message line in addition to the post script.",
        )
        self.assertEqual("PS", message_lines[-1])

        self.assertEqual(
            len(targets), task.scm.add.call_count, "Expected one call to scm.add per artifact"
        )

        self.assertEqual(
            len(targets), task.scm.tag.call_count, "Expected one call to scm.tag per artifact"
        )
        args, kwargs = task.scm.tag.call_args
        tag_name, tag_message = args
        tag_message_splitlines = tag_message.splitlines()
        self.assertTrue(
            len(tag_message_splitlines) > 1,
            "Expected at least one tag message line in addition to the post script.",
        )
        self.assertEqual("PS", tag_message_splitlines[-1])

    def test_publish_retry_works(self):
        self.set_options(dryrun=False, scm_push_attempts=3, repos=self._get_repos())
        task = self.create_task(self.context(target_roots=self._create_nail_target()))
        self._prepare_mocks(task)

        task.scm.push = Mock()
        task.scm.push.side_effect = FailNTimes(2, Scm.RemoteException)
        task.execute()
        # Two failures, one success
        self.assertEqual(2 + 1, task.scm.push.call_count)

    def test_publish_retry_eventually_fails(self):
        # confirm that we fail if we have too many failed push attempts
        self.set_options(dryrun=False, scm_push_attempts=3, repos=self._get_repos())
        task = self.create_task(self.context(target_roots=self._create_nail_target()))
        self._prepare_mocks(task)
        task.scm.push = Mock()
        task.scm.push.side_effect = FailNTimes(3, Scm.RemoteException)
        with self.assertRaises(Scm.RemoteException):
            task.execute()

    def test_publish_retry_fails_immediately_with_exception_on_refresh_failure(self):
        self.set_options(dryrun=False, scm_push_attempts=3, repos=self._get_repos())
        task = self.create_task(self.context(target_roots=self._create_nail_target()))

        self._prepare_mocks(task)
        task.scm.push = Mock()
        task.scm.push.side_effect = FailNTimes(3, Scm.RemoteException)
        task.scm.refresh = Mock()
        task.scm.refresh.side_effect = FailNTimes(1, Scm.LocalException)

        with self.assertRaises(Scm.LocalException):
            task.execute()
        self.assertEqual(1, task.scm.push.call_count)

    def test_publish_local_only(self):
        with self.assertRaises(TaskError):
            self.create_task(self.context())

    def test_check_targets_fails_with_duplicate_artifacts(self):
        bad_targets = self._prepare_targets_with_duplicates()
        with temporary_dir() as publishdir:
            self.set_options(dryrun=False, local=publishdir)
            task = self.create_task(self.context(target_roots=bad_targets))
            self._prepare_mocks(task)
            with self.assertRaises(JarPublish.DuplicateArtifactError):
                task.check_targets(task.exported_targets())


class FailNTimes:
    def __init__(self, tries, exc_type, success=None):
        self.tries = tries
        self.exc_type = exc_type
        self.success = success

    def __call__(self, *args, **kwargs):
        self.tries -= 1
        if self.tries >= 0:
            raise self.exc_type()
        else:
            return self.success


class FailNTimesTest(unittest.TestCase):
    def test_fail_n_times(self):
        with self.assertRaises(ValueError):
            foo = Mock()
            foo.bar.side_effect = FailNTimes(1, ValueError)
            foo.bar()

        foo.bar()


class JarPublishAuthTest(NailgunTaskTestBase):
    """Tests for backend jvm JarPublish class."""

    def _default_jvm_opts(self):
        """Return a fresh copy of this list every time."""
        return ["jvm_opt_1", "jvm_opt_2"]

    @classmethod
    def task_type(cls):
        return JarPublish

    def setUp(self):
        super().setUp()

        self.set_options(
            jvm_options=["-Dfoo=bar"],
            repos={
                "some_ext_repo": {
                    "resolver": "artifactory.foobar.com",
                    "confs": ["default", "sources"],
                    "auth": "",
                    "help": "You break it, you bought it",
                }
            },
        )
        context = self.context()
        self._jar_publish = self.create_task(context)

    def test_options_with_no_auth(self):
        """When called without authentication credentials, `JarPublish._ivy_jvm_options()` shouldn't
        modify any options."""
        self._jar_publish._jvm_options = self._default_jvm_opts()
        repo = {}
        modified_opts = self._jar_publish._ivy_jvm_options(repo)
        self.assertEqual(modified_opts, self._default_jvm_opts())

    def test_options_with_auth(self):
        """`JarPublish._ivy_jvm_options()` should produce the same list, when called multiple times
        with authentication credentials."""
        self._jar_publish._jvm_options = self._default_jvm_opts()

        username = "mjk"
        password = "h."
        creds_options = [f"-Dlogin={username}", f"-Dpassword={password}"]

        repo = {
            "auth": "blah",
            "username": username,
            "password": password,
        }
        modified_opts = self._jar_publish._ivy_jvm_options(repo)
        self.assertEqual(modified_opts, self._default_jvm_opts() + creds_options)

        # Now run it again, and make sure we don't get dupes.
        modified_opts = self._jar_publish._ivy_jvm_options(repo)
        self.assertEqual(modified_opts, self._default_jvm_opts() + creds_options)
