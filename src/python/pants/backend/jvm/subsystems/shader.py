# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import re
from collections import namedtuple

logger = logging.getLogger(__name__)


class UnaryRule(namedtuple("UnaryRule", ["name", "pattern"])):
    """Base class for shading keep and zap rules specifiable in BUILD files."""

    def render(self):
        return f"{self.name} {self.pattern}\n"


class RelocateRule(namedtuple("Rule", ["from_pattern", "to_pattern"])):
    """Base class for shading relocation rules specifiable in BUILD files."""

    _wildcard_pattern = re.compile("[*]+")
    _starts_with_number_pattern = re.compile("^[0-9]")
    _illegal_package_char_pattern = re.compile("[^a-z0-9_]", re.I)

    @classmethod
    def _infer_shaded_pattern_iter(cls, from_pattern, prefix=None):
        if prefix:
            yield prefix
        last = 0
        for i, match in enumerate(cls._wildcard_pattern.finditer(from_pattern)):
            yield from_pattern[last : match.start()]
            yield f"@{i + 1}"
            last = match.end()
        yield from_pattern[last:]

    @classmethod
    def new(cls, from_pattern, shade_pattern=None, shade_prefix=None):
        if not shade_pattern:
            shade_pattern = "".join(cls._infer_shaded_pattern_iter(from_pattern, shade_prefix))
        return cls(from_pattern, shade_pattern)

    def render(self):
        return f"rule {self.from_pattern} {self.to_pattern}\n"


class Shading:
    """Wrapper around relocate and exclude shading rules exposed in BUILD files."""

    SHADE_PREFIX = "__shaded_by_pants__."
    """The default shading package."""

    @classmethod
    def create_keep(cls, pattern):
        """Creates a rule which marks classes matching the given pattern as roots.

        If any keep rules are set, all classes that are not reachable from roots are removed from the
        jar.

        Examples: ::

            # Only include classes reachable from Main.
            shading_keep('org.foobar.example.Main')

            # Only keep classes reachable from the example package.
            shading_keep('org.foobar.example.*')

        :param string pattern: Any fully-qualified classname which matches this pattern will be kept as
          a root. '*' is a wildcard that matches any individual package component, and '**' is a
          wildcard that matches any trailing pattern (ie the rest of the string).
        """
        return UnaryRule("keep", pattern)

    @classmethod
    def create_zap(cls, pattern):
        """Creates a rule which removes matching classes from the jar.

        Examples: ::

            # Remove the main class.
            shading_zap('org.foobar.example.Main')

            # Remove everything in the example package.
            shading_keep('org.foobar.example.*')

        :param string pattern: Any fully-qualified classname which matches this pattern will removed
          from the jar. '*' is a wildcard that matches any individual package component, and '**' is a
          wildcard that matches any trailing pattern (ie the rest of the string).
        """
        return UnaryRule("zap", pattern)

    @classmethod
    def create_relocate(cls, from_pattern, shade_pattern=None, shade_prefix=None):
        """Creates a rule which shades jar entries from one pattern to another.

        Examples: ::

            # Rename everything in the org.foobar.example package
            # to __shaded_by_pants__.org.foobar.example.
            shading_relocate('org.foobar.example.**')

            # Rename org.foobar.example.Main to __shaded_by_pants__.org.foobar.example.Main
            shading_relocate('org.foobar.example.Main')

            # Rename org.foobar.example.Main to org.foobar.example.NotMain
            shading_relocate('org.foobar.example.Main', 'org.foobar.example.NotMain')

            # Rename all 'Main' classes under any direct subpackage of org.foobar.
            shading_relocate('org.foobar.*.Main')

            # Rename org.foobar package to com.barfoo package
            shading_relocate('org.foobar.**', 'com.barfoo.@1')

            # Rename everything in org.foobar.example package to __hello__.org.foobar.example
            shading_relocate('org.foobar.example.**', shade_prefix='__hello__')

        :param string from_pattern: Any fully-qualified classname which matches this pattern will be
          shaded. '*' is a wildcard that matches any individual package component, and '**' is a
          wildcard that matches any trailing pattern (ie the rest of the string).
        :param string shade_pattern: The shaded pattern to use, where ``@1``, ``@2``, ``@3``, etc are
          references to the groups matched by wildcards (groups are numbered from left to right). If
          omitted, this pattern is inferred from the input pattern, prefixed by the ``shade_prefix``
          (if provided). (Eg, a ``from_pattern`` of ``com.*.foo.bar.**`` implies a default
          ``shade_pattern`` of ``__shaded_by_pants__.com.@1.foo.@2``)
        :param string shade_prefix: Prefix to prepend when generating a ``shade_pattern`` (if a
          ``shade_pattern`` is not provided by the user). Defaults to '``__shaded_by_pants__.``'.
        """
        # NB(gmalmquist): Have have to check "is None" rather than using an or statement, because the
        # empty-string is a valid prefix which should not be replaced by the default prefix.
        shade_prefix = Shading.SHADE_PREFIX if shade_prefix is None else shade_prefix
        return RelocateRule.new(from_pattern, shade_pattern, shade_prefix)

    @classmethod
    def create_exclude(cls, pattern):
        """Creates a rule which excludes the given pattern from shading.

        Examples: ::

            # Don't shade the org.foobar.example.Main class
            shading_exclude('org.foobar.example.Main')

            # Don't shade anything under org.foobar.example
            shading_exclude('org.foobar.example.**')

        :param string pattern: Any fully-qualified classname which matches this pattern will NOT be
          shaded. '*' is a wildcard that matches any individual package component, and '**' is a
          wildcard that matches any trailing pattern (ie the rest of the string).
        """
        return cls.create_relocate(pattern, shade_prefix="")

    @classmethod
    def create_keep_package(cls, package_name, recursive=True):
        """Convenience constructor for a package keep rule.

        Essentially equivalent to just using ``shading_keep('package_name.**')``.

        :param string package_name: Package name to keep (eg, ``org.pantsbuild.example``).
        :param bool recursive: Whether to keep everything under any subpackage of ``package_name``,
          or just direct children of the package. (Defaults to True).
        """
        return cls.create_keep(cls._format_package_glob(package_name, recursive))

    @classmethod
    def create_zap_package(cls, package_name, recursive=True):
        """Convenience constructor for a package zap rule.

        Essentially equivalent to just using ``shading_zap('package_name.**')``.

        :param string package_name: Package name to remove (eg, ``org.pantsbuild.example``).
        :param bool recursive: Whether to remove everything under any subpackage of ``package_name``,
          or just direct children of the package. (Defaults to True).
        """
        return cls.create_zap(cls._format_package_glob(package_name, recursive))

    @classmethod
    def create_relocate_package(cls, package_name, shade_prefix=None, recursive=True):
        """Convenience constructor for a package relocation rule.

        Essentially equivalent to just using ``shading_relocate('package_name.**')``.

        :param string package_name: Package name to shade (eg, ``org.pantsbuild.example``).
        :param string shade_prefix: Optional prefix to apply to the package. Defaults to
          ``__shaded_by_pants__.``.
        :param bool recursive: Whether to rename everything under any subpackage of ``package_name``,
          or just direct children of the package. (Defaults to True).
        """
        return cls.create_relocate(
            from_pattern=cls._format_package_glob(package_name, recursive),
            shade_prefix=shade_prefix,
        )

    @classmethod
    def create_exclude_package(cls, package_name, recursive=True):
        """Convenience constructor for a package exclusion rule.

        Essentially equivalent to just using ``shading_exclude('package_name.**')``.

        :param string package_name: Package name to exclude (eg, ``org.pantsbuild.example``).
        :param bool recursive: Whether to exclude everything under any subpackage of ``package_name``,
          or just direct children of the package. (Defaults to True).
        """
        return cls.create_relocate(
            from_pattern=cls._format_package_glob(package_name, recursive), shade_prefix=""
        )

    @classmethod
    def _format_package_glob(cls, package_name, recursive=True):
        return f"{package_name}.{'**' if recursive else '*'}"
