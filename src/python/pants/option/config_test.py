# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import configparser
from dataclasses import dataclass
from textwrap import dedent
from typing import Dict

import pytest

from pants.option.config import Config, TomlSerializer
from pants.testutil.test_base import TestBase
from pants.util.contextutil import temporary_file
from pants.util.ordered_set import OrderedSet


@dataclass(frozen=True)
class ConfigFile:
    content: str
    default_values: Dict
    expected_options: Dict


FILE_1 = ConfigFile(
    content=dedent(
        """
        [DEFAULT]
        name = "foo"
        answer = 42
        scale = 1.2
        path = "/a/b/%(answer)s"
        embed = "%(path)s::foo"
        disclaimer = '''
        Let it be known
        that.'''

        [a]
        # TODO: once TOML releases its new version with support for heterogenous lists, we should be
        # able to rewrite this to `[1, 2, 3, "%(answer)s"`. See
        # https://github.com/toml-lang/toml/issues/665.
        list = ["1", "2", "3", "%(answer)s"]
        list2.add = [7, 8, 9]
        list3.remove = ["x", "y", "z"]

        [b]
        preempt = true

        [b.nested]
        dict = '''
        {
          "a": 1,
          "b": "%(answer)s",
          "c": ["%(answer)s", "%(answer)s"],
        }'''

        [b.nested.nested-again]
        movie = "inception"

        [c]
        name = "overridden_from_default"
        interpolated_from_section = "%(name)s is interpolated"
        recursively_interpolated_from_section = "%(interpolated_from_section)s (again)"
        """
    ),
    default_values={
        "name": "foo",
        "answer": "42",
        "scale": "1.2",
        "path": "/a/b/42",
        "embed": "/a/b/42::foo",
        "disclaimer": "Let it be known\nthat.",
    },
    expected_options={
        "a": {"list": '["1", "2", "3", "42"]', "list2": "+[7, 8, 9]", "list3": '-["x", "y", "z"]'},
        "b": {"preempt": "True"},
        "b.nested": {"dict": '{\n  "a": 1,\n  "b": "42",\n  "c": ["42", "42"],\n}'},
        "b.nested.nested-again": {"movie": "inception"},
        "c": {
            "name": "overridden_from_default",
            "interpolated_from_section": "overridden_from_default is interpolated",
            "recursively_interpolated_from_section": "overridden_from_default is interpolated (again)",
        },
    },
)


FILE_2 = ConfigFile(
    content=dedent(
        """
        [a]
        fast = true

        [b]
        preempt = false

        [d]
        list.add = [0, 1]
        list.remove = [8, 9]

        [empty_section]

        [p.child]
        no_values_in_parent = true
        """
    ),
    default_values={},
    expected_options={
        "a": {"fast": "True"},
        "b": {"preempt": "False"},
        "d": {"list": "+[0, 1],-[8, 9]"},
        "empty_section": {},
        "p.child": {"no_values_in_parent": "True"},
    },
)


class ConfigeTest(TestBase):
    def _setup_config(self) -> Config:
        with temporary_file(binary_mode=False, suffix=".toml") as config1, temporary_file(
            binary_mode=False, suffix=".toml"
        ) as config2:
            config1.write(FILE_1.content)
            config1.close()
            config2.write(FILE_2.content)
            config2.close()
            parsed_config = Config.load(
                config_paths=[config1.name, config2.name],
                seed_values={"buildroot": self.build_root},
            )
            assert [config1.name, config2.name] == parsed_config.sources()
        return parsed_config

    def setUp(self) -> None:
        self.config = self._setup_config()
        self.default_seed_values = Config._determine_seed_values(
            seed_values={"buildroot": self.build_root},
        )
        self.expected_combined_values = {
            **FILE_1.expected_options,
            **FILE_2.expected_options,
            "a": {**FILE_2.expected_options["a"], **FILE_1.expected_options["a"]},
        }

    def test_sections(self) -> None:
        expected_sections = list(
            OrderedSet([*FILE_2.expected_options.keys(), *FILE_1.expected_options.keys()])
        )
        assert self.config.sections() == expected_sections
        for section in expected_sections:
            assert self.config.has_section(section) is True
        # We should only look at explicitly defined sections. For example, if `cache.java` is
        # defined but `cache` is not, then `cache` should not be included in the sections.
        assert self.config.has_section("p") is False

    def test_has_option(self) -> None:
        # Check has all DEFAULT values
        for default_option in (*self.default_seed_values.keys(), *FILE_1.default_values.keys()):
            assert self.config.has_option(section="DEFAULT", option=default_option) is True
        # Check every explicitly defined section has its options + the seed defaults
        for section, options in self.expected_combined_values.items():
            for option in (*options, *self.default_seed_values):
                assert self.config.has_option(section=section, option=option) is True
        # Check every section for file1 also has file1's DEFAULT values
        for section in FILE_1.expected_options:
            for option in FILE_1.default_values:
                assert self.config.has_option(section=section, option=option) is True
        # Check that file1's DEFAULT values don't apply to sections only defined in file2
        sections_only_in_file2 = set(FILE_2.expected_options.keys()) - set(
            FILE_1.expected_options.keys()
        )
        for section in sections_only_in_file2:
            for option in FILE_1.default_values:
                assert self.config.has_option(section=section, option=option) is False
        # Check that non-existent options are False
        nonexistent_options = {
            "DEFAULT": "fake",
            "a": "fake",
            "b": "fast",
        }
        for section, option in nonexistent_options.items():
            assert self.config.has_option(section=section, option=option) is False
        # Check that sections aren't misclassified as options
        nested_sections = {
            "b": "nested",
            "b.nested": "nested-again",
            "p": "child",
        }
        for parent_section, child_section in nested_sections.items():
            assert self.config.has_option(section=parent_section, option=child_section) is False

    def test_list_all_options(self) -> None:
        # This is used in `options_bootstrapper.py` to validate that every option is recognized.
        file1_config = self.config.configs()[1]
        file2_config = self.config.configs()[0]
        for section, options in FILE_1.expected_options.items():
            expected = list(options.keys())
            expected.extend(
                default_option
                for default_option in (
                    *self.default_seed_values.keys(),
                    *FILE_1.default_values.keys(),
                )
                if default_option not in expected
            )
            assert file1_config.values.options(section=section) == expected
        for section, options in FILE_2.expected_options.items():
            assert file2_config.values.options(section=section) == [
                *options.keys(),
                *self.default_seed_values.keys(),
            ]
        # Check non-existent section
        for config in file1_config, file2_config:
            with pytest.raises(configparser.NoSectionError):
                config.values.options("fake")

    def test_default_values(self) -> None:
        # This is used in `options_bootstrapper.py` to ignore default values when validating options.
        file1_config = self.config.configs()[1]
        file2_config = self.config.configs()[0]
        # NB: string interpolation should only happen when calling _ConfigValues.get_value(). The
        # values for _ConfigValues.defaults are not yet interpolated.
        default_file1_values_unexpanded = {
            **FILE_1.default_values,
            "path": "/a/b/%(answer)s",
            "embed": "%(path)s::foo",
        }
        assert file1_config.values.defaults == {
            **self.default_seed_values,
            **default_file1_values_unexpanded,
        }
        assert file2_config.values.defaults == self.default_seed_values

    def test_get(self) -> None:
        # Check the DEFAULT section
        for option, value in {**self.default_seed_values, **FILE_1.default_values}.items():
            assert self.config.get(section="DEFAULT", option=option) == value
        # Check the combined values, including that each section has the default seed values
        for section, section_values in self.expected_combined_values.items():
            for option, value in {**section_values, **self.default_seed_values}.items():
                assert self.config.get(section=section, option=option) == value
        # Check that each section from file1 also has file1's default values, unless that section
        # explicitly overrides the default
        for section, section_values in FILE_1.expected_options.items():
            for option, default_value in FILE_1.default_values.items():
                expected = default_value if option not in section_values else section_values[option]
                assert self.config.get(section=section, option=option) == expected

        def check_defaults(default: str) -> None:
            assert self.config.get(section="c", option="fast") is None
            assert self.config.get(section="c", option="preempt", default=None) is None
            assert self.config.get(section="c", option="jake", default=default) == default

        check_defaults("")
        check_defaults("42")

    def test_empty(self) -> None:
        config = Config.load([])
        assert config.sections() == []
        assert config.sources() == []
        assert config.has_section("DEFAULT") is False
        assert config.has_option(section="DEFAULT", option="name") is False


def test_toml_serializer() -> None:
    original_values: Dict = {
        "GLOBAL": {
            "truthy": True,
            "falsy": False,
            "int": 0,
            "float": 0.0,
            "word": "hello there",
            "listy": ["a", "b", "c"],
            "map": {"a": 0, "b": 1},
        },
        "cache.java": {"o": ""},
        "inception.nested.nested-again.one-more": {"o": ""},
    }
    assert TomlSerializer(original_values).normalize() == {
        "GLOBAL": {**original_values["GLOBAL"], "map": "{'a': 0, 'b': 1}"},
        "cache": {"java": {"o": ""}},
        "inception": {"nested": {"nested-again": {"one-more": {"o": ""}}}},
    }
