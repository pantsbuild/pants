# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from functools import total_ordering

from pants.base.exceptions import TaskError
from pants.base.revision import Revision
from pants.java.distribution.distribution import DistributionLocator
from pants.option.option_util import flatten_shlexed_list
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_method, memoized_property

logger = logging.getLogger(__name__)


class JvmPlatform(Subsystem):
    """Used to keep track of repo compile and runtime settings for jvm targets.

    JvmPlatform covers both compile time and runtime jvm platform settings. A platform is a group of
    compile time and runtime configurations.

    See src/docs/common_tasks/multiple_jvm_versions.md for more detail.
    """

    # NB: These assume a java version number N can be specified as either 'N' or '1.N'
    # (eg, '7' is equivalent to '1.7'). Java stopped following this convention starting with Java 9,
    # so this list does not go past it.
    SUPPORTED_CONVERSION_VERSIONS = (6, 7, 8)

    _COMPILER_CHOICES = ["zinc", "javac", "rsc"]

    class IllegalDefaultPlatform(TaskError):
        """The --default-platform option was set, but isn't defined in --platforms."""

    class UndefinedJvmPlatform(TaskError):
        """Platform isn't defined."""

        def __init__(self, target, platform_name, platforms_by_name):
            scope_name = JvmPlatform.options_scope
            messages = [
                'Undefined jvm platform "{}" (referenced by {}).'.format(
                    platform_name, target.address.spec if target else "unknown target"
                )
            ]
            if not platforms_by_name:
                messages.append(
                    "In fact, no platforms are defined under {0}. These should typically be"
                    " specified in [{0}] in pants.toml.".format(scope_name)
                )
            else:
                messages.append(
                    "Perhaps you meant one of:{}".format(
                        "".join("\n  {}".format(name) for name in sorted(platforms_by_name.keys()))
                    )
                )
                messages.append(
                    "\nThese are typically defined under [{}] in pants.toml.".format(scope_name)
                )
            super(JvmPlatform.UndefinedJvmPlatform, self).__init__(" ".join(messages))

    options_scope = "jvm-platform"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--platforms",
            advanced=True,
            type=dict,
            default={},
            fingerprint=True,
            help="Compile settings that can be referred to by name in jvm_targets.",
        )
        register(
            "--default-platform",
            advanced=True,
            type=str,
            default=None,
            fingerprint=True,
            help="Name of the default platform to use for compilation. If default-runtime-platform"
            " is None, also applies to runtime. Used when targets leave platform unspecified.",
        )
        register(
            "--default-runtime-platform",
            advanced=True,
            type=str,
            default=None,
            fingerprint=True,
            help="Name of the default runtime platform. Used when targets leave runtime_platform"
            " unspecified.",
        )
        register(
            "--compiler",
            advanced=True,
            choices=cls._COMPILER_CHOICES,
            default="rsc",
            fingerprint=True,
            help="Java compiler implementation to use.",
        )

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (DistributionLocator,)

    def _parse_platform(self, name, platform):
        return JvmPlatformSettings(
            source_level=platform.get("source", platform.get("target")),
            target_level=platform.get("target", platform.get("source")),
            args=platform.get("args", ()),
            jvm_options=platform.get("jvm_options", ()),
            name=name,
        )

    @classmethod
    def preferred_jvm_distribution(cls, platforms, strict=False, jdk=False):
        """Returns a jvm Distribution with a version that should work for all the platforms.

        Any one of those distributions whose version is >= all requested platforms' versions
        can be returned unless strict flag is set.

        :param iterable platforms: An iterable of platform settings.
        :param bool strict: If true, only distribution whose version matches the minimum
          required version can be returned, i.e, the max target_level of all the requested
          platforms.
        :param bool jdk: If true, the distribution must be a JDK.
        :returns: Distribution one of the selected distributions.
        """
        if not platforms:
            return DistributionLocator.cached(jdk=jdk)
        min_version = max(platform.target_level for platform in platforms)
        max_version = Revision(*(min_version.components + [9999])) if strict else None
        return DistributionLocator.cached(
            minimum_version=min_version, maximum_version=max_version, jdk=jdk
        )

    @memoized_property
    def platforms_by_name(self):
        platforms = self.get_options().platforms or {}
        return {name: self._parse_platform(name, platform) for name, platform in platforms.items()}

    @property
    def _fallback_platform(self):
        logger.warning("No default jvm platform is defined.")
        source_level = JvmPlatform.parse_java_version(DistributionLocator.cached().version)
        target_level = source_level
        platform_name = f"(DistributionLocator.cached().version {source_level})"
        return JvmPlatformSettings(
            source_level=source_level,
            target_level=target_level,
            args=[],
            jvm_options=[],
            name=platform_name,
        )

    @memoized_property
    def default_platform(self):
        name = self.get_options().default_platform
        if not name:
            return self._fallback_platform
        platforms_by_name = self.platforms_by_name
        if name not in platforms_by_name:
            raise self.IllegalDefaultPlatform(
                "The default platform was set to '{0}', but no platform by that name has been "
                "defined. Typically, this should be defined under [{1}] in pants.toml.".format(
                    name, self.options_scope
                )
            )
        return JvmPlatformSettings._copy_as_default(platforms_by_name[name], name=name)

    @memoized_property
    def default_runtime_platform(self):
        name = self.get_options().default_runtime_platform
        if not name:
            return self.default_platform
        platforms_by_name = self.platforms_by_name
        if name not in platforms_by_name:
            raise self.IllegalDefaultPlatform(
                "The default runtime platform was set to '{0}', but no platform by that name has been "
                "defined. Typically, this should be defined under [{1}] in pants.toml.".format(
                    name, self.options_scope
                )
            )
        return JvmPlatformSettings._copy_as_default(platforms_by_name[name], name=name)

    @memoized_method
    def get_platform_by_name(self, name, for_target=None):
        """Finds the platform with the given name.

        If the name is empty or None, returns the default platform.
        If not platform with the given name is defined, raises an error.
        :param str name: name of the platform.
        :param JvmTarget for_target: optionally specified target we're looking up the platform for.
          Only used in error message generation.
        :return: The jvm platform object.
        :rtype: JvmPlatformSettings
        """
        if not name:
            return self.default_platform
        if name not in self.platforms_by_name:
            raise self.UndefinedJvmPlatform(for_target, name, self.platforms_by_name)
        return self.platforms_by_name[name]

    def get_platform_for_target(self, target):
        """Find the platform associated with this target.

        :param JvmTarget target: target to query.
        :return: The jvm platform object.
        :rtype: JvmPlatformSettings
        """
        if not target.payload.platform and target.is_synthetic:
            derived_from = target.derived_from
            platform = derived_from and getattr(derived_from, "platform", None)
            if platform:
                return platform
        return self.get_platform_by_name(target.payload.platform, target)

    def get_runtime_platform_for_target(self, target):
        """Find the runtime platform associated with this target.

        :param JvmTarget,RuntimePlatformMixin target: target to query.
        :return: The jvm platform object.
        :rtype: JvmPlatformSettings
        """
        # Lookup order
        # - target's declared runtime_platform
        # - default runtime_platform
        # - target's declared platform
        # - default platform
        target_runtime_platform = target.payload.runtime_platform
        if not target_runtime_platform and target.is_synthetic:
            derived_from = target.derived_from
            platform = derived_from and getattr(derived_from, "runtime_platform", None)
            if platform:
                return platform
        if target_runtime_platform:
            return self.get_platform_by_name(target_runtime_platform, target)
        elif self.default_runtime_platform:
            return self.default_runtime_platform
        else:
            return self.get_platform_for_target(target)

    @classmethod
    def parse_java_version(cls, version):
        """Parses the java version (given a string or Revision object).

        Handles java version-isms, converting things like '7' -> '1.7' appropriately.

        Truncates input versions down to just the major and minor numbers (eg, 1.6), ignoring extra
        versioning information after the second number.

        :param version: the input version, given as a string or Revision object.
        :return: the parsed and cleaned version, suitable as a javac -source or -target argument.
        :rtype: Revision
        """
        conversion = {str(i): f"1.{i}" for i in cls.SUPPORTED_CONVERSION_VERSIONS}
        if str(version) in conversion:
            return Revision.lenient(conversion[str(version)])

        if not hasattr(version, "components"):
            version = Revision.lenient(version)
        if len(version.components) <= 2:
            return version
        return Revision(*version.components[:2])


@total_ordering
class JvmPlatformSettings:
    """Simple information holder to keep track of common arguments to java compilers."""

    class IllegalSourceTargetCombination(TaskError):
        """Illegal pair of -source and -target flags to compile java."""

    @staticmethod
    def _copy_as_default(original, name):
        """Copies the original with a new name, setting by_default to True."""
        return JvmPlatformSettings(
            source_level=original.source_level,
            target_level=original.target_level,
            args=original.args,
            jvm_options=original.jvm_options,
            name=name,
            by_default=True,
        )

    def __init__(
        self, *, source_level, target_level, args, jvm_options, name=None, by_default=False
    ):
        """
    :param source_level: Revision object or string for the java source level.
    :param target_level: Revision object or string for the java target level.
    :param list args: Additional arguments to pass to the java compiler.
    :param list jvm_options: Additional jvm options specific to this JVM platform.
    :param str name: name to identify this platform.
    :param by_default: True if this value was inferred by omission of a specific platform setting.
    """
        self.source_level = JvmPlatform.parse_java_version(source_level)
        self.target_level = JvmPlatform.parse_java_version(target_level)
        self.args = tuple(flatten_shlexed_list(args or ()))
        self.jvm_options = tuple(flatten_shlexed_list(jvm_options or ()))
        self.name = name
        self._by_default = by_default
        self._validate_source_target()

    def _validate_source_target(self):
        if self.source_level > self.target_level:
            if self.by_default:
                name = f"{self.name} (by default)"
            else:
                name = self.name
            raise self.IllegalSourceTargetCombination(
                "Platform {platform} has java source level {source_level} but target level {target_level}.".format(
                    platform=name, source_level=self.source_level, target_level=self.target_level
                )
            )

    @property
    def by_default(self):
        return self._by_default

    def _tuple(self):
        return (
            self.source_level,
            self.target_level,
            self.args,
            self.jvm_options,
        )

    def __eq__(self, other):
        return self._tuple() == other._tuple()

    # TODO(#6071): decide if this should raise NotImplemented on invalid comparisons
    def __lt__(self, other):
        return self._tuple() < other._tuple()

    def __hash__(self):
        return hash(self._tuple())

    def __str__(self):
        return (
            "JvmPlatformSettings(source={source},target={target},args=({args}),"
            "jvm_options={jvm_options})".format(
                source=self.source_level,
                target=self.target_level,
                args=" ".join(self.args),
                jvm_options=" ".join(self.jvm_options),
            )
        )
