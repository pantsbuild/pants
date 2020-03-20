# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform, JvmPlatformSettings
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.targets.runtime_platform_mixin import RuntimePlatformMixin
from pants.base.payload import Payload
from pants.base.revision import Revision
from pants.testutil.subsystem.util import init_subsystem
from pants.testutil.test_base import TestBase


class HasRuntimePlatform(RuntimePlatformMixin, JvmTarget):
    def __init__(self, payload=None, runtime_platform=None, **kwargs):
        payload = payload or Payload()
        super(HasRuntimePlatform, self).__init__(
            payload=payload, runtime_platform=runtime_platform, **kwargs
        )


class JvmPlatformTest(TestBase):
    def test_runtime_lookup_both_defaults(self):
        init_subsystem(
            JvmPlatform,
            options={
                "jvm-platform": {
                    "platforms": {
                        "default-platform": {"target": "8"},
                        "default-runtime-platform": {"target": "8"},
                        "target-platform": {"target": "8"},
                        "target-runtime-platform": {"target": "8"},
                    },
                    "default_platform": "default-platform",
                    "default_runtime_platform": "default-runtime-platform",
                }
            },
        )

        without_platforms = self.make_target("//:without-platforms", HasRuntimePlatform)
        just_platform = self.make_target(
            "//:with-platform", HasRuntimePlatform, platform="target-platform"
        )
        just_runtime_platform = self.make_target(
            "//:with-runtime-platform",
            HasRuntimePlatform,
            runtime_platform="target-runtime-platform",
        )
        both_platforms = self.make_target(
            "//:with-platform-and-runtime-platform",
            HasRuntimePlatform,
            platform="target-platform",
            runtime_platform="target-runtime-platform",
        )

        instance = JvmPlatform.global_instance()
        assert (
            instance.get_runtime_platform_for_target(without_platforms).name
            == "default-runtime-platform"
        )
        assert (
            instance.get_runtime_platform_for_target(just_platform).name
            == "default-runtime-platform"
        )
        assert (
            instance.get_runtime_platform_for_target(just_runtime_platform).name
            == "target-runtime-platform"
        )
        assert (
            instance.get_runtime_platform_for_target(both_platforms).name
            == "target-runtime-platform"
        )

    def test_runtime_lookup_no_default_runtime_platform(self):
        init_subsystem(
            JvmPlatform,
            options={
                "jvm-platform": {
                    "platforms": {
                        "default-platform": {"target": "8"},
                        "default-runtime-platform": {"target": "8"},
                        "target-platform": {"target": "8"},
                        "target-runtime-platform": {"target": "8"},
                    },
                    "default_platform": "default-platform",
                    "default_runtime_platform": None,
                }
            },
        )

        without_platforms = self.make_target("//:without-platforms", HasRuntimePlatform)
        just_platform = self.make_target(
            "//:with-platform", HasRuntimePlatform, platform="target-platform"
        )
        just_runtime_platform = self.make_target(
            "//:with-runtime-platform",
            HasRuntimePlatform,
            runtime_platform="target-runtime-platform",
        )
        both_platforms = self.make_target(
            "//:with-platform-and-runtime-platform",
            HasRuntimePlatform,
            platform="target-platform",
            runtime_platform="target-runtime-platform",
        )

        instance = JvmPlatform.global_instance()
        assert (
            instance.get_runtime_platform_for_target(without_platforms).name == "default-platform"
        )
        assert instance.get_runtime_platform_for_target(just_platform).name == "default-platform"
        assert (
            instance.get_runtime_platform_for_target(just_runtime_platform).name
            == "target-runtime-platform"
        )
        assert (
            instance.get_runtime_platform_for_target(both_platforms).name
            == "target-runtime-platform"
        )

    def test_synthetic_target_runtime_platform_lookup(self):
        init_subsystem(
            JvmPlatform,
            options={
                "jvm-platform": {
                    "platforms": {
                        "default-platform": {"target": "8"},
                        "default-runtime-platform": {"target": "8"},
                        "target-platform": {"target": "8"},
                        "target-runtime-platform": {"target": "8"},
                        "parent-target-platform": {"target": "8"},
                        "parent-target-runtime-platform": {"target": "8"},
                    },
                    "default_platform": "default-platform",
                    "default_runtime_platform": None,
                }
            },
        )

        just_platform = self.make_target(
            "//:parent-with-runtime-platform", HasRuntimePlatform, platform="parent-target-platform"
        )
        just_runtime_platform = self.make_target(
            "//:parent-with-platform",
            HasRuntimePlatform,
            runtime_platform="parent-target-runtime-platform",
        )

        synth_none = self.make_target(
            "//:without-platforms",
            HasRuntimePlatform,
            synthetic=True,
            derived_from=just_runtime_platform,
        )
        synth_just_platform = self.make_target(
            "//:with-platform",
            HasRuntimePlatform,
            synthetic=True,
            derived_from=just_runtime_platform,
            platform="target-platform",
        )
        synth_just_runtime = self.make_target(
            "//:with-runtime-platform",
            HasRuntimePlatform,
            synthetic=True,
            derived_from=just_runtime_platform,
            runtime_platform="target-runtime-platform",
        )
        synth_both = self.make_target(
            "//:with-platform-and-runtime-platform",
            HasRuntimePlatform,
            synthetic=True,
            derived_from=just_runtime_platform,
            platform="target-platform",
            runtime_platform="target-runtime-platform",
        )
        synth_just_platform_with_parent_same = self.make_target(
            "//:with-platform-and-platform-parent",
            HasRuntimePlatform,
            synthetic=True,
            derived_from=just_platform,
            platform="target-platform",
        )

        instance = JvmPlatform.global_instance()
        assert (
            instance.get_runtime_platform_for_target(synth_none).name
            == "parent-target-runtime-platform"
        )
        assert (
            instance.get_runtime_platform_for_target(synth_just_platform).name
            == "parent-target-runtime-platform"
        )
        assert (
            instance.get_runtime_platform_for_target(synth_just_runtime).name
            == "target-runtime-platform"
        )
        assert (
            instance.get_runtime_platform_for_target(synth_both).name == "target-runtime-platform"
        )
        assert (
            instance.get_runtime_platform_for_target(synth_just_platform_with_parent_same).name
            == "default-platform"
        )

    def test_strict_usage(self):
        init_subsystem(
            JvmPlatform,
            options={
                "jvm-platform": {
                    "platforms": {
                        "default-platform": {"target": "9"},
                        "8-platform": {"target": "8"},
                        "10-platform": {"target": "10"},
                        "11-platform": {"target": "11"},
                        "strict-8-platform": {"target": "8", "strict": True},
                        "strict-10-platform": {"target": "10", "strict": True},
                        "strict-11-platform": {"target": "11", "strict": True},
                    },
                    "default_platform": "default-platform",
                    "default_runtime_platform": None,
                }
            },
        )
        instance = JvmPlatform.global_instance()
        strict_8_platform = instance.get_platform_by_name("strict-8-platform")
        default_9_platform = instance.default_platform
        # TODO maybe this should use the runtime platform
        assert instance._preferred_jvm_distribution_args([]) == {
            "jdk": False,
        }
        assert JvmPlatform._preferred_jvm_distribution_args([default_9_platform]) == {
            "minimum_version": Revision.lenient("9.0.0"),
            "maximum_version": None,
            "jdk": False,
        }
        assert JvmPlatform._preferred_jvm_distribution_args([default_9_platform], strict=True) == {
            "minimum_version": Revision.lenient("9.0.0"),
            "maximum_version": Revision.lenient("9.0.9999"),
            "jdk": False,
        }
        assert instance._preferred_jvm_distribution_args([strict_8_platform]) == {
            "minimum_version": Revision.lenient("1.8.0"),
            "maximum_version": Revision.lenient("1.8.9999"),
            "jdk": False,
        }
        assert instance._preferred_jvm_distribution_args([strict_8_platform], strict=False) == {
            "minimum_version": Revision.lenient("1.8.0"),
            "maximum_version": None,
            "jdk": False,
        }
        # strict/non-strict platform requested together--not strict (maybe should be strict?)
        # when there are strict platforms in a collection, use those
        # as long as
        # - equal to the max target in the collection
        # - > the min target in the collection
        # - equivalent to any other strict platforms in the collection
        # strict has to be highest requested version
        assert JvmPlatform._preferred_jvm_distribution_args(
            [strict_8_platform, default_9_platform]
        ) == {"minimum_version": Revision.lenient("9.0.0"), "maximum_version": None, "jdk": False,}

        with self.assertRaisesRegex(Exception, "wut"):
            # requested strict 8 & lenient 9.
            # fail because 9 is lower bound
            JvmPlatform._preferred_jvm_distribution_args(
            [
                instance.get_platform_by_name("9-platform"),
                instance.get_platform_by_name("strict-8-platform"),
            ])
        with self.assertRaisesRegex(Exception, "WUT"):
            # two different strict platforms can't work
            JvmPlatform._preferred_jvm_distribution_args(
            [
                instance.get_platform_by_name("strict-9-platform"),
                instance.get_platform_by_name("strict-8-platform"),
            ])
        # two of the same strict platform thumbs up
        JvmPlatform._preferred_jvm_distribution_args(
            [
                instance.get_platform_by_name("strict-8-platform"),
                instance.get_platform_by_name("strict-8-platform"),
            ])
        # strict highest, matching highest non-strict, other non-strict
        JvmPlatform._preferred_jvm_distribution_args(
            [
                instance.get_platform_by_name("strict-11-platform"),
                instance.get_platform_by_name("11-platform"),
                instance.get_platform_by_name("10-platform"),
            ])


def test_jvm_options(self):
        init_subsystem(
            JvmPlatform,
            options={
                "jvm-platform": {
                    "platforms": {
                        "platform-with-jvm-options": {
                            "target": "8",
                            "jvm_options": ["-Dsomething"],
                        },
                        "platform-without-jvm-options": {"target": "8"},
                    },
                }
            },
        )
        instance = JvmPlatform.global_instance()
        with_options = instance.get_platform_by_name("platform-with-jvm-options")
        without_options = instance.get_platform_by_name("platform-without-jvm-options")

        assert ("-Dsomething",) == with_options.jvm_options
        assert tuple() == without_options.jvm_options

    def test_jvm_options_from_platform_shlexed(self):
        init_subsystem(
            JvmPlatform,
            options={
                "jvm-platform": {
                    "platforms": {
                        "platform-with-shlexable-vm-options": {
                            "target": "8",
                            "jvm_options": ["-Dsomething -Dsomethingelse"],
                        },
                    },
                }
            },
        )
        instance = JvmPlatform.global_instance()
        need_shlex_options = instance.get_platform_by_name("platform-with-shlexable-vm-options")

        assert ("-Dsomething", "-Dsomethingelse") == need_shlex_options.jvm_options

    def test_compile_setting_equivalence(self):
        assert JvmPlatformSettings(
            source_level="11", target_level="11", args=["-Xfoo:bar"], jvm_options=[]
        ) == JvmPlatformSettings(
            source_level="11", target_level="11", args=["-Xfoo:bar"], jvm_options=[]
        )
        assert JvmPlatformSettings(
            source_level="11", target_level="11", args=[], jvm_options=["-Xfoo:bar"]
        ) == JvmPlatformSettings(
            source_level="11", target_level="11", args=[], jvm_options=["-Xfoo:bar"]
        )

    def test_compile_setting_inequivalence(self):
        assert JvmPlatformSettings(
            source_level="11", target_level="11", args=[], jvm_options=[]
        ) != JvmPlatformSettings(source_level="11", target_level="12", args=[], jvm_options=[])

        assert JvmPlatformSettings(
            source_level="11", target_level="11", args=["-Xfoo:bar"], jvm_options=[]
        ) != JvmPlatformSettings(
            source_level="11", target_level="11", args=["-XSomethingElse"], jvm_options=[]
        )

        assert JvmPlatformSettings(
            source_level="9", target_level="11", args=[], jvm_options=[]
        ) != JvmPlatformSettings(source_level="11", target_level="11", args=[], jvm_options=[])

        assert JvmPlatformSettings(
            source_level="11", target_level="11", args=[], jvm_options=["-Xvmsomething"]
        ) != JvmPlatformSettings(source_level="11", target_level="11", args=[], jvm_options=[])

    def test_incompatible_source_target_level_raises_error(self):
        with self.assertRaises(JvmPlatformSettings.IllegalSourceTargetCombination):
            JvmPlatformSettings(source_level="11", target_level="9", args=[], jvm_options=[])
