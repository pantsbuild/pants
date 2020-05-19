# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from collections import defaultdict
from contextlib import contextmanager
from functools import reduce

from pants.backend.jvm.subsystems.jvm_platform import JvmPlatformSettings
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.jvm_compile.jvm_compile import JvmCompile
from pants.backend.jvm.tasks.jvm_compile.rsc.rsc_compile import RscCompile
from pants.base.revision import Revision
from pants.java.distribution.distribution import DistributionLocator
from pants.subsystem.subsystem import Subsystem
from pants.testutil.jvm.nailgun_task_test_base import NailgunTaskTestBase
from pants.testutil.subsystem.util import init_subsystem
from pants.util.memo import memoized_method
from pants.util.osutil import get_os_name, normalize_os_name
from pants_test.java.distribution.test_distribution import EXE, distribution


class JavaCompileSettingsPartitioningTest(NailgunTaskTestBase):
    @classmethod
    def task_type(cls):
        return RscCompile

    def _java(self, name, platform=None, deps=None):
        return self.make_target(
            spec=f"java:{name}",
            target_type=JavaLibrary,
            platform=platform,
            dependencies=deps or [],
            sources=[],
        )

    def _platforms(self, *versions):
        return {str(v): {"source": str(v)} for v in versions}

    @memoized_method
    def _version(self, version):
        return Revision.lenient(version)

    def _task_setup(self, targets, platforms=None, default_platform=None, **options):
        options["source"] = options.get("source", "13")
        options["target"] = options.get("target", "13")
        self.set_options(**options)
        self.set_options_for_scope(
            "jvm-platform", platforms=platforms, default_platform=default_platform
        )
        context = self.context(target_roots=targets)
        return self.create_task(context)

    def _settings_and_targets(self, targets, **options):
        self._task_setup(targets, **options)
        settings_and_targets = defaultdict(set)
        for target in targets:
            settings_and_targets[target.platform].add(target)
        return list(settings_and_targets.items())

    def _partition(self, targets, **options):
        self._task_setup(targets, **options)
        partition = defaultdict(set)
        for target in targets:
            partition[target.platform.target_level].add(target)
        return partition

    def _format_partition(self, partition):
        return "{{{}\n  }}".format(
            ",".join(
                "\n    {}: [{}]".format(key, ", ".join(sorted(t.address.spec for t in value)))
                for key, value in sorted(partition.items())
            )
        )

    @staticmethod
    def _format_zinc_arguments(settings, distribution):
        zinc_args = [
            "-C-source",
            f"-C{settings.source_level}",
            "-C-target",
            f"-C{settings.target_level}",
        ]
        if settings.args:
            settings_args = settings.args
            if any("$JAVA_HOME" in a for a in settings.args):
                settings_args = (a.replace("$JAVA_HOME", distribution.home) for a in settings.args)
            zinc_args.extend(settings_args)
        return zinc_args

    def assert_partitions_equal(self, expected, received):
        # Convert to normal dicts and remove empty values.
        expected = {key: set(val) for key, val in expected.items() if val}
        received = {key: set(val) for key, val in received.items() if val}
        self.assertEqual(
            expected,
            received,
            "Partitions are different!\n  expected: {}\n  received: {}".format(
                self._format_partition(expected), self._format_partition(received)
            ),
        )

    def test_single_target(self):
        java11 = self._java("eleven", "11")
        partition = self._partition([java11], platforms=self._platforms("11"))
        self.assertEqual(1, len(partition))
        self.assertEqual({java11}, set(partition[self._version("11")]))

    def test_independent_targets(self):
        java11 = self._java("eleven", "11")
        java12 = self._java("twelve", "12")
        java13 = self._java("thirteen", "13")
        partition = self._partition(
            [java11, java12, java13], platforms=self._platforms("11", "12", "13")
        )
        expected = {
            self._version(java.payload.platform): {java} for java in (java11, java12, java13)
        }
        self.assertEqual(3, len(partition))
        self.assert_partitions_equal(expected, partition)

    def test_java_version_aliases(self):
        # NB: This feature is only supported for Java 6-8. Java 9+ must be referred to, for example,
        # as `9`, not `1.9`.
        expected = {}
        for version in (6, 7, 8):
            expected[Revision.lenient(f"1.{version}")] = {
                self._java(f"j1{version}", f"1.{version}"),
                self._java(f"j{version}", f"{version}"),
            }
        partition = self._partition(
            list(reduce(set.union, list(expected.values()), set())),
            platforms=self._platforms("6", "7", "8", "1.6", "1.7", "1.8"),
        )
        self.assertEqual(len(expected), len(partition))
        self.assert_partitions_equal(expected, partition)

    def test_valid_dependent_targets(self):
        java11 = self._java("eleven", "11")
        java12 = self._java("twelve", "12")
        java13 = self._java("thirteen", "13", deps=[java11])

        partition = self._partition(
            [java11, java12, java13], platforms=self._platforms("11", "12", "13")
        )
        self.assert_partitions_equal(
            {
                self._version("11"): {java11},
                self._version("12"): {java12},
                self._version("13"): {java13},
            },
            partition,
        )

    def test_unspecified_default(self):
        java = self._java("unspecified", None)
        java11 = self._java("eleven", "11", deps=[java])
        java12 = self._java("twelve", "12", deps=[java])
        partition = self._partition(
            [java12, java, java11],
            source="11",
            target="11",
            platforms=self._platforms("11", "12"),
            default_platform="11",
        )
        self.assert_partitions_equal(
            {self._version("11"): {java, java11}, self._version("12"): {java12}}, partition
        )

    def test_invalid_source_target_combination_by_jvm_platform(self):
        java_wrong = self._java("source7target6", "bad")
        with self.assertRaises(JvmPlatformSettings.IllegalSourceTargetCombination):
            self._settings_and_targets(
                [java_wrong], platforms={"bad": {"source": "12", "target": "11"}}
            )

    def test_valid_source_target_combination(self):
        platforms = {
            "java9_10": {"source": "9", "target": "10"},
            "java10_11": {"source": "10", "target": "11"},
            "java9_11": {"source": "9", "target": "11"},
        }
        self._settings_and_targets(
            [
                self._java("java9_10", "java9_10"),
                self._java("java10_11", "java10_11"),
                self._java("java9_11", "java9_11"),
            ],
            platforms=platforms,
        )

    def _get_zinc_arguments(self, settings):
        distribution = JvmCompile._local_jvm_distribution(settings=settings)
        return self._format_zinc_arguments(settings, distribution)

    def test_java_home_extraction(self):
        init_subsystem(DistributionLocator)
        _, source, _, target, foo, bar, composite, single = tuple(
            self._get_zinc_arguments(
                JvmPlatformSettings(
                    source_level="1.8",
                    target_level="1.8",
                    args=["foo", "bar", "foo:$JAVA_HOME/bar:$JAVA_HOME/foobar", "$JAVA_HOME"],
                    jvm_options=[],
                )
            )
        )

        self.assertEqual("-C1.8", source)
        self.assertEqual("-C1.8", target)
        self.assertEqual("foo", foo)
        self.assertEqual("bar", bar)
        self.assertNotEqual("$JAVA_HOME", single)
        self.assertNotIn("$JAVA_HOME", composite)
        self.assertEqual(f"foo:{single}/bar:{single}/foobar", composite)

    def test_java_home_extraction_empty(self):
        init_subsystem(DistributionLocator)
        platform_settings = JvmPlatformSettings(
            source_level="1.8", target_level="1.8", args=[], jvm_options=[]
        )
        result = tuple(self._get_zinc_arguments(platform_settings))
        self.assertEqual(
            4, len(result), msg="_get_zinc_arguments did not correctly handle empty args."
        )

    def test_java_home_extraction_missing_distributions(self):
        # This will need to be bumped if java ever gets to major version one million.
        far_future_version = "999999.1"
        farther_future_version = "999999.2"

        os_name = normalize_os_name(get_os_name())

        @contextmanager
        def fake_distributions(versions):
            """Create a fake JDK for each java version in the input, and yield the list of
            java_homes.

            :param list versions: List of java version strings.
            """
            fakes = []
            for version in versions:
                fakes.append(
                    distribution(executables=[EXE("bin/java", version), EXE("bin/javac", version)],)
                )
            yield [d.__enter__() for d in fakes]
            for d in fakes:
                d.__exit__(None, None, None)

        @contextmanager
        def fake_distribution_locator(*versions):
            """Sets up a fake distribution locator with fake distributions.

            Creates one distribution for each java version passed as an argument, and yields a list
            of paths to the java homes for each distribution.
            """
            with fake_distributions(versions) as paths:
                path_options = {DistributionLocator.options_scope: {"paths": {os_name: paths}}}
                Subsystem.reset()
                init_subsystem(DistributionLocator, options=path_options)
                yield paths

        # Completely missing a usable distribution.
        with fake_distribution_locator(far_future_version):
            with self.assertRaises(DistributionLocator.Error):
                self._get_zinc_arguments(
                    JvmPlatformSettings(
                        source_level=farther_future_version,
                        target_level=farther_future_version,
                        args=["$JAVA_HOME/foo"],
                        jvm_options=[],
                    )
                )

        # Missing a strict distribution.
        with fake_distribution_locator(farther_future_version) as paths:
            results = self._get_zinc_arguments(
                JvmPlatformSettings(
                    source_level=far_future_version,
                    target_level=far_future_version,
                    args=["$JAVA_HOME/foo", "$JAVA_HOME"],
                    jvm_options=[],
                )
            )
            self.assertEqual(paths[0], results[-1])
            self.assertEqual(f"{paths[0]}/foo", results[-2])

        # Make sure we pick up the strictest possible distribution.
        with fake_distribution_locator(farther_future_version, far_future_version) as paths:
            farer_path, far_path = paths
            results = self._get_zinc_arguments(
                JvmPlatformSettings(
                    source_level=far_future_version,
                    target_level=far_future_version,
                    args=["$JAVA_HOME/foo", "$JAVA_HOME"],
                    jvm_options=[],
                )
            )
            self.assertEqual(far_path, results[-1])
            self.assertEqual(f"{far_path}/foo", results[-2])

        # Make sure we pick the higher distribution when the lower one doesn't work.
        with fake_distribution_locator(farther_future_version, far_future_version) as paths:
            farer_path, far_path = paths
            results = self._get_zinc_arguments(
                JvmPlatformSettings(
                    source_level=farther_future_version,
                    target_level=farther_future_version,
                    args=["$JAVA_HOME/foo", "$JAVA_HOME"],
                    jvm_options=[],
                )
            )
            self.assertEqual(farer_path, results[-1])
            self.assertEqual(f"{farer_path}/foo", results[-2])
