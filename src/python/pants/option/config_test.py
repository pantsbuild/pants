# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest
from dataclasses import dataclass
from textwrap import dedent
from typing import Dict

import pytest

from pants.engine.fs import FileContent
from pants.option.config import Config, TomlSerializer
from pants.option.errors import NoSectionError
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

        [c]
        name = "overridden_from_default"
        interpolated_from_section = "%(name)s is interpolated"
        recursively_interpolated_from_section = "%(interpolated_from_section)s (again)"

        [d.dict_val]
        # Make sure we don't misinterpret `add` and `remove` as list options.
        add = 0
        remove = 0
        nested = { nested_key = 'foo' }
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
        "c": {
            "name": "overridden_from_default",
            "interpolated_from_section": "overridden_from_default is interpolated",
            "recursively_interpolated_from_section": "overridden_from_default is interpolated (again)",
        },
        "d": {"dict_val": "{'add': 0, 'remove': 0, 'nested': {'nested_key': 'foo'}"},
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
        """
    ),
    default_values={},
    expected_options={
        "a": {"fast": "True"},
        "b": {"preempt": "False"},
        "d": {"list": "+[0, 1],-[8, 9]"},
        "empty_section": {},
    },
)


def _setup_config() -> Config:
    parsed_config = Config.load(
        file_contents=[
            FileContent("file1.toml", FILE_1.content.encode()),
            FileContent("file2.toml", FILE_2.content.encode()),
        ],
        seed_values={"buildroot": "fake_buildroot"},
    )
    assert ["file1.toml", "file2.toml"] == parsed_config.sources()
    return parsed_config


class ConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = _setup_config()
        self.default_seed_values = Config._determine_seed_values(
            seed_values={"buildroot": "fake_buildroot"},
        )
        self.expected_combined_values = {
            **FILE_1.expected_options,
            **FILE_2.expected_options,
            "a": {**FILE_2.expected_options["a"], **FILE_1.expected_options["a"]},
        }

    def test_sections(self) -> None:
        expected_sections = OrderedSet(
            [*FILE_2.expected_options.keys(), *FILE_1.expected_options.keys()]
        )
        assert self.config.sections() == list(expected_sections)
        for section in expected_sections:
            assert self.config.has_section(section) is True

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
            with pytest.raises(NoSectionError):
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
        "some-subsystem": {"o": ""},
    }
    assert TomlSerializer(original_values).normalize() == {
        "GLOBAL": {**original_values["GLOBAL"], "map": "{'a': 0, 'b': 1}"},
        "some-subsystem": {"o": ""},
    }


def test_toml_serializer_list_add_remove() -> None:
    original_values = {"GLOBAL": {"backend_packages.add": ["added"]}}
    assert TomlSerializer(original_values).normalize() == {  # type: ignore[arg-type]
        "GLOBAL": {"backend_packages": "+['added']"}
    }
