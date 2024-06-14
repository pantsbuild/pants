# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import re
from textwrap import dedent
from typing import Any, Mapping, cast

import pytest

from pants.build_graph.address import BuildFileAddressRequest, MaybeAddress, ResolveError
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.core.target_types import GenericTarget
from pants.engine.addresses import Address, AddressInput, BuildFileAddress
from pants.engine.env_vars import CompleteEnvironmentVars, EnvironmentVars, EnvironmentVarsRequest
from pants.engine.fs import DigestContents, FileContent, PathGlobs
from pants.engine.internals.build_files import (
    AddressFamilyDir,
    BUILDFileEnvVarExtractor,
    BuildFileOptions,
    BuildFileSyntaxError,
    OptionalAddressFamily,
    evaluate_preludes,
    parse_address_family,
)
from pants.engine.internals.defaults import ParametrizeDefault
from pants.engine.internals.dep_rules import MaybeBuildFileDependencyRulesImplementation
from pants.engine.internals.mapper import AddressFamily
from pants.engine.internals.parametrize import Parametrize
from pants.engine.internals.parser import BuildFilePreludeSymbols, BuildFileSymbolInfo, Parser
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.internals.session import SessionValues
from pants.engine.internals.synthetic_targets import (
    SyntheticAddressMaps,
    SyntheticAddressMapsRequest,
)
from pants.engine.internals.target_adaptor import TargetAdaptor, TargetAdaptorRequest
from pants.engine.target import (
    Dependencies,
    MultipleSourcesField,
    OverridesField,
    RegisteredTargetTypes,
    SingleSourceField,
    StringField,
    Tags,
    Target,
    TargetFilesGenerator,
)
from pants.engine.unions import UnionMembership
from pants.init.bootstrap_scheduler import BootstrapStatus
from pants.testutil.pytest_util import assert_logged
from pants.testutil.rule_runner import (
    MockGet,
    QueryRule,
    RuleRunner,
    engine_error,
    run_rule_with_mocks,
)
from pants.util.frozendict import FrozenDict
from pants.util.strutil import softwrap


def test_parse_address_family_empty() -> None:
    """Test that parsing an empty BUILD file results in an empty AddressFamily."""
    optional_af = run_rule_with_mocks(
        parse_address_family,
        rule_args=[
            Parser(
                build_root="",
                registered_target_types=RegisteredTargetTypes({}),
                union_membership=UnionMembership({}),
                object_aliases=BuildFileAliases(),
                ignore_unrecognized_symbols=False,
            ),
            BootstrapStatus(in_progress=False),
            BuildFileOptions(("BUILD",)),
            BuildFilePreludeSymbols(FrozenDict(), ()),
            AddressFamilyDir("/dev/null"),
            RegisteredTargetTypes({}),
            UnionMembership({}),
            MaybeBuildFileDependencyRulesImplementation(None),
            SessionValues({CompleteEnvironmentVars: CompleteEnvironmentVars({})}),
        ],
        mock_gets=[
            MockGet(
                output_type=DigestContents,
                input_types=(PathGlobs,),
                mock=lambda _: DigestContents([FileContent(path="/dev/null/BUILD", content=b"")]),
            ),
            MockGet(
                output_type=OptionalAddressFamily,
                input_types=(AddressFamilyDir,),
                mock=lambda _: OptionalAddressFamily("/dev"),
            ),
            MockGet(
                output_type=SyntheticAddressMaps,
                input_types=(SyntheticAddressMapsRequest,),
                mock=lambda _: SyntheticAddressMaps(),
            ),
            MockGet(
                output_type=EnvironmentVars,
                input_types=(EnvironmentVarsRequest, CompleteEnvironmentVars),
                mock=lambda _1, _2: EnvironmentVars({}),
            ),
        ],
    )
    assert optional_af.path == "/dev/null"
    assert optional_af.address_family is not None
    af = optional_af.address_family
    assert af.namespace == "/dev/null"
    assert len(af.name_to_target_adaptors) == 0


def run_prelude_parsing_rule(prelude_content: str) -> BuildFilePreludeSymbols:
    symbols = run_rule_with_mocks(
        evaluate_preludes,
        rule_args=[
            BuildFileOptions((), prelude_globs=("prelude",)),
            Parser(
                build_root="",
                registered_target_types=RegisteredTargetTypes({"target": GenericTarget}),
                union_membership=UnionMembership({}),
                object_aliases=BuildFileAliases(),
                ignore_unrecognized_symbols=False,
            ),
        ],
        mock_gets=[
            MockGet(
                output_type=DigestContents,
                input_types=(PathGlobs,),
                mock=lambda _: DigestContents(
                    [FileContent(path="/dev/null/prelude", content=prelude_content.encode())]
                ),
            ),
        ],
    )
    return cast(BuildFilePreludeSymbols, symbols)


def test_prelude_parsing_good() -> None:
    prelude_content = dedent(
        """
        def bar():
            __defaults__(all=dict(ok=123))
            return build_file_dir()

        def foo():
            return 1
        """
    )
    result = run_prelude_parsing_rule(prelude_content)
    assert result.symbols["foo"]() == 1


def test_prelude_parsing_syntax_error() -> None:
    with pytest.raises(
        Exception, match="Error parsing prelude file /dev/null/prelude: name 'blah' is not defined"
    ):
        run_prelude_parsing_rule("blah")


def test_prelude_parsing_illegal_import() -> None:
    prelude_content = dedent(
        """\
        import os
        def make_target():
            python_sources()
        """
    )
    with pytest.raises(
        Exception,
        match="Import used in /dev/null/prelude at line 1\\. Import statements are banned",
    ):
        run_prelude_parsing_rule(prelude_content)


def test_prelude_check_filepath() -> None:
    prelude_content = dedent(
        """
        build_file_dir()
        """
    )
    with pytest.raises(
        Exception,
        match="The BUILD file symbol `build_file_dir` may only be used in BUILD files\\. If used",
    ):
        run_prelude_parsing_rule(prelude_content)


def test_prelude_check_defaults() -> None:
    prelude_content = dedent(
        """
        __defaults__(all=dict(bad=123))
        """
    )
    with pytest.raises(
        Exception,
        match="The BUILD file symbol `__defaults__` may only be used in BUILD files\\. If used",
    ):
        run_prelude_parsing_rule(prelude_content)


def test_prelude_check_env() -> None:
    prelude_content = dedent(
        """
        env("nope")
        """
    )
    with pytest.raises(
        Exception,
        match="The BUILD file symbol `env` may only be used in BUILD files\\. If used",
    ):
        run_prelude_parsing_rule(prelude_content)


def test_prelude_exceptions() -> None:
    prelude_content = dedent(
        """\
        def abort():
            raise ValueError
        """
    )
    result = run_prelude_parsing_rule(prelude_content)
    assert "ValueError" not in result.symbols
    with pytest.raises(ValueError):
        result.symbols["abort"]()


def test_prelude_references_builtin_symbols() -> None:
    prelude_content = dedent(
        """\
        def make_a_target():
            # Can't call it outside of the context of a BUILD file, less we get internal errors
            target
        """
    )
    result = run_prelude_parsing_rule(prelude_content)
    # In the real world, this would define the target (note it doesn't need to return, as BUILD files
    # don't). In the test we're just ensuring we don't get a `NameError`
    result.symbols["make_a_target"]()


def test_prelude_type_hint_code() -> None:
    # Issue 18435
    prelude_content = dedent(
        """\
        def ecr_docker_image(
            *,
            name: Optional[str] = None,
            dependencies: Optional[List[str]] = None,
            image_tags: Optional[List[str]] = None,
            git_tag_prefix: Optional[str] = None,
            latest_tag_prefix: Optional[str] = None,
            buildcache_tag: str = "buildcache",
            image_labels: Optional[Mapping[str, str]] = None,
            tags: Optional[List[str]] = None,
            extra_build_args: Optional[List[str]] = None,
            source: Optional[str] = None,
            target_stage: Optional[str] = None,
            instructions: Optional[List[str]] = None,
            repository: Optional[str] = None,
            context_root: Optional[str] = None,
            push_in_pants_ci: bool = True,
            push_latest: bool = False,
        ) -> int:
            return 42
        """
    )
    result = run_prelude_parsing_rule(prelude_content)
    ecr_docker_image = result.info["ecr_docker_image"]
    assert ecr_docker_image.signature in (
        (
            "(*,"
            " name: Optional[str] = None,"
            " dependencies: Optional[List[str]] = None,"
            " image_tags: Optional[List[str]] = None,"
            " git_tag_prefix: Optional[str] = None,"
            " latest_tag_prefix: Optional[str] = None,"
            " buildcache_tag: str = 'buildcache',"
            " image_labels: Optional[Mapping[str, str]] = None,"
            " tags: Optional[List[str]] = None,"
            " extra_build_args: Optional[List[str]] = None,"
            " source: Optional[str] = None,"
            " target_stage: Optional[str] = None,"
            " instructions: Optional[List[str]] = None,"
            " repository: Optional[str] = None,"
            " context_root: Optional[str] = None,"
            " push_in_pants_ci: bool = True,"
            " push_latest: bool = False"
            ") -> int"
        ),
        (
            "(*,"
            " name: Union[str, NoneType] = None,"
            " dependencies: Union[List[str], NoneType] = None,"
            " image_tags: Union[List[str], NoneType] = None,"
            " git_tag_prefix: Union[str, NoneType] = None,"
            " latest_tag_prefix: Union[str, NoneType] = None,"
            " buildcache_tag: str = 'buildcache',"
            " image_labels: Union[Mapping[str, str], NoneType] = None,"
            " tags: Union[List[str], NoneType] = None,"
            " extra_build_args: Union[List[str], NoneType] = None,"
            " source: Union[str, NoneType] = None,"
            " target_stage: Union[str, NoneType] = None,"
            " instructions: Union[List[str], NoneType] = None,"
            " repository: Union[str, NoneType] = None,"
            " context_root: Union[str, NoneType] = None,"
            " push_in_pants_ci: bool = True,"
            " push_latest: bool = False"
            ") -> int"
        ),
    )
    assert 42 == ecr_docker_image.value()


def test_prelude_docstring_on_function() -> None:
    macro_docstring = "This is the doc-string for `macro_func`."
    prelude_content = dedent(
        f"""
        def macro_func(arg: int) -> str:
            '''{macro_docstring}'''
            pass
        """
    )
    result = run_prelude_parsing_rule(prelude_content)
    info = result.info["macro_func"]
    assert BuildFileSymbolInfo("macro_func", result.symbols["macro_func"]) == info
    assert macro_docstring == info.help
    assert "(arg: int) -> str" == info.signature
    assert {"macro_func"} == set(result.info)


def test_prelude_docstring_on_constant() -> None:
    macro_docstring = """This is the doc-string for `MACRO_CONST`.

    Use weird indentations.

    On purpose.
    """
    prelude_content = dedent(
        f"""
        Number = NewType("Number", int)
        MACRO_CONST: Annotated[str, Doc({macro_docstring!r})] = "value"
        MULTI_HINTS: Annotated[Number, "unrelated", Doc("this is it"), 24] = 42
        ANON: str = "undocumented"
        _PRIVATE: int = 42
        untyped = True
        """
    )
    result = run_prelude_parsing_rule(prelude_content)
    assert {"MACRO_CONST", "ANON", "Number", "MULTI_HINTS", "untyped"} == set(result.info)

    info = result.info["MACRO_CONST"]
    assert info.value == "value"
    assert info.help == softwrap(macro_docstring)
    assert info.signature == ": str"

    multi = result.info["MULTI_HINTS"]
    assert multi.value == 42
    assert multi.help == "this is it"
    assert multi.signature == ": Number"

    anon = result.info["ANON"]
    assert anon.value == "undocumented"
    assert anon.help is None
    assert anon.signature == ": str"


def test_prelude_reference_env_vars() -> None:
    prelude_content = dedent(
        """
        def macro():
            env("MY_ENV")
        """
    )
    result = run_prelude_parsing_rule(prelude_content)
    assert ("MY_ENV",) == result.referenced_env_vars


class ResolveField(StringField):
    alias = "resolve"


class MockDepsField(Dependencies):
    pass


class MockMultipleSourcesField(MultipleSourcesField):
    default = ("*.mock",)


class MockTgt(Target):
    alias = "mock_tgt"
    core_fields = (MockDepsField, MockMultipleSourcesField, Tags, ResolveField)


class MockSingleSourceField(SingleSourceField):
    pass


class MockGeneratedTarget(Target):
    alias = "generated"
    core_fields = (MockDepsField, Tags, MockSingleSourceField, ResolveField)


class MockTargetGenerator(TargetFilesGenerator):
    alias = "generator"
    core_fields = (MockMultipleSourcesField, OverridesField)
    generated_target_cls = MockGeneratedTarget
    copied_fields = ()
    moved_fields = (MockDepsField, Tags, ResolveField)


def test_resolve_address() -> None:
    rule_runner = RuleRunner(
        rules=[QueryRule(Address, [AddressInput]), QueryRule(MaybeAddress, [AddressInput])]
    )
    rule_runner.write_files({"a/b/c.txt": "", "f.txt": ""})

    def assert_is_expected(address_input: AddressInput, expected: Address) -> None:
        assert rule_runner.request(Address, [address_input]) == expected

    assert_is_expected(
        AddressInput.parse("a/b/c.txt", description_of_origin="tests"),
        Address("a/b", target_name=None, relative_file_path="c.txt"),
    )
    assert_is_expected(
        AddressInput.parse("a/b", description_of_origin="tests"),
        Address("a/b", target_name=None, relative_file_path=None),
    )

    assert_is_expected(
        AddressInput.parse("a/b:c", description_of_origin="tests"),
        Address("a/b", target_name="c"),
    )
    assert_is_expected(
        AddressInput.parse("a/b/c.txt:c", description_of_origin="tests"),
        Address("a/b", relative_file_path="c.txt", target_name="c"),
    )

    # Top-level addresses will not have a path_component, unless they are a file address.
    assert_is_expected(
        AddressInput.parse("f.txt:original", description_of_origin="tests"),
        Address("", relative_file_path="f.txt", target_name="original"),
    )
    assert_is_expected(
        AddressInput.parse("//:t", description_of_origin="tests"),
        Address("", target_name="t"),
    )

    bad_address_input = AddressInput.parse("a/b/fake", description_of_origin="tests")
    expected_err = "'a/b/fake' does not exist on disk"
    with engine_error(ResolveError, contains=expected_err):
        rule_runner.request(Address, [bad_address_input])
    maybe_addr = rule_runner.request(MaybeAddress, [bad_address_input])
    assert isinstance(maybe_addr.val, ResolveError)
    assert expected_err in str(maybe_addr.val)


@pytest.fixture
def target_adaptor_rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[QueryRule(TargetAdaptor, (TargetAdaptorRequest,))],
        target_types=[MockTgt, MockGeneratedTarget, MockTargetGenerator],
        objects={"parametrize": Parametrize},
    )


def test_target_adaptor_parsed_correctly(target_adaptor_rule_runner: RuleRunner) -> None:
    target_adaptor_rule_runner.write_files(
        {
            "helloworld/dir/BUILD": dedent(
                """\
                mock_tgt(
                    fake_field=42,
                    dependencies=[
                        # Because we don't follow dependencies or even parse dependencies, this
                        # self-cycle should be fine.
                        ":dir",
                        ":sibling",
                        "helloworld/util",
                        "helloworld/util:tests",
                    ],
                    build_file_dir=f"build file's dir is: {build_file_dir()}"
                )

                mock_tgt(name='t2')
                """
            )
        }
    )
    target_adaptor = target_adaptor_rule_runner.request(
        TargetAdaptor,
        [TargetAdaptorRequest(Address("helloworld/dir"), description_of_origin="tests")],
    )
    assert target_adaptor.name is None
    assert target_adaptor.type_alias == "mock_tgt"
    assert target_adaptor.kwargs["dependencies"] == [
        ":dir",
        ":sibling",
        "helloworld/util",
        "helloworld/util:tests",
    ]
    # NB: TargetAdaptors do not validate what fields are valid. The Target API should error
    # when encountering this, but it's fine at this stage.
    assert target_adaptor.kwargs["fake_field"] == 42
    assert target_adaptor.kwargs["build_file_dir"] == "build file's dir is: helloworld/dir"

    target_adaptor = target_adaptor_rule_runner.request(
        TargetAdaptor,
        [
            TargetAdaptorRequest(
                Address("helloworld/dir", target_name="t2"), description_of_origin="tests"
            )
        ],
    )
    assert target_adaptor.name == "t2"
    assert target_adaptor.type_alias == "mock_tgt"


def test_target_adaptor_defaults_applied(target_adaptor_rule_runner: RuleRunner) -> None:
    target_adaptor_rule_runner.write_files(
        {
            "helloworld/dir/BUILD": dedent(
                """\
                __defaults__({mock_tgt: dict(resolve="mock")}, all=dict(tags=["24"]))
                mock_tgt(tags=["42"])
                mock_tgt(name='t2')
                """
            )
        }
    )
    target_adaptor = target_adaptor_rule_runner.request(
        TargetAdaptor,
        [TargetAdaptorRequest(Address("helloworld/dir"), description_of_origin="tests")],
    )
    assert target_adaptor.name is None
    assert target_adaptor.kwargs["resolve"] == "mock"
    assert target_adaptor.kwargs["tags"] == ["42"]

    target_adaptor = target_adaptor_rule_runner.request(
        TargetAdaptor,
        [
            TargetAdaptorRequest(
                Address("helloworld/dir", target_name="t2"), description_of_origin="tests"
            )
        ],
    )
    assert target_adaptor.name == "t2"
    assert target_adaptor.kwargs["resolve"] == "mock"

    # The defaults are not frozen until after the BUILD file have been fully parsed, so this is a
    # list rather than a tuple at this time.
    assert target_adaptor.kwargs["tags"] == ["24"]


def test_generated_target_defaults(target_adaptor_rule_runner: RuleRunner) -> None:
    target_adaptor_rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                __defaults__({generated: dict(resolve="mock")}, all=dict(tags=["24"]))
                generated(name="explicit", tags=["42"], source="e.txt")
                generator(name='gen', sources=["g*.txt"])
                """
            ),
            "e.txt": "",
            "g1.txt": "",
            "g2.txt": "",
        }
    )

    explicit_target = target_adaptor_rule_runner.get_target(Address("", target_name="explicit"))
    assert explicit_target.address.target_name == "explicit"
    assert explicit_target.get(ResolveField).value == "mock"
    assert explicit_target.get(Tags).value == ("42",)

    implicit_target = target_adaptor_rule_runner.get_target(
        Address("", target_name="gen", relative_file_path="g1.txt")
    )
    assert str(implicit_target.address) == "//g1.txt:gen"
    assert implicit_target.get(ResolveField).value == "mock"
    assert implicit_target.get(Tags).value == ("24",)


def test_inherit_defaults(target_adaptor_rule_runner: RuleRunner) -> None:
    target_adaptor_rule_runner.write_files(
        {
            "BUILD": """__defaults__(all=dict(tags=["root"]))""",
            "helloworld/dir/BUILD": dedent(
                """\
                __defaults__({mock_tgt: dict(resolve="mock")}, extend=True)
                mock_tgt()
                """
            ),
        }
    )
    target_adaptor = target_adaptor_rule_runner.request(
        TargetAdaptor,
        [TargetAdaptorRequest(Address("helloworld/dir"), description_of_origin="tests")],
    )
    assert target_adaptor.name is None
    assert target_adaptor.kwargs["resolve"] == "mock"

    # The defaults originates from a parent BUILD file, and as such has been frozen.
    assert target_adaptor.kwargs["tags"] == ("root",)


def test_parametrize_defaults(target_adaptor_rule_runner: RuleRunner) -> None:
    target_adaptor_rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                __defaults__(
                  all=dict(
                    tags=parametrize(a=["a", "root"], b=["non-root", "b"])
                  )
                )
                """
            ),
            "helloworld/dir/BUILD": "mock_tgt()",
        }
    )
    target_adaptor = target_adaptor_rule_runner.request(
        TargetAdaptor,
        [TargetAdaptorRequest(Address("helloworld/dir"), description_of_origin="tests")],
    )
    assert target_adaptor.kwargs["tags"] == ParametrizeDefault(a=("a", "root"), b=("non-root", "b"))


def test_parametrized_groups(target_adaptor_rule_runner: RuleRunner) -> None:
    def _determenistic_parametrize_group_keys(value: Mapping[str, Any]) -> dict[str, Any]:
        # The `parametrize` object uses a unique generated field name when splatted onto a target
        # (in order to provide a helpful error message in case of non-unique group names), but the
        # part up until `:` is determenistic on the group name, which we need to exploit in the
        # tests using parametrize groups.
        return {key.rsplit(":", 1)[0]: val for key, val in value.items()}

    target_adaptor_rule_runner.write_files(
        {
            "hello/BUILD": dedent(
                """\
                mock_tgt(
                  description="desc for a and b",
                  **parametrize("a", tags=["opt-a"], resolve="lock-a"),
                  **parametrize("b", tags=["opt-b"], resolve="lock-b"),
                )
                """
            ),
        }
    )

    target_adaptor = target_adaptor_rule_runner.request(
        TargetAdaptor,
        [TargetAdaptorRequest(Address("hello"), description_of_origin="tests")],
    )
    assert _determenistic_parametrize_group_keys(
        target_adaptor.kwargs
    ) == _determenistic_parametrize_group_keys(
        dict(
            description="desc for a and b",
            **Parametrize("a", tags=["opt-a"], resolve="lock-a"),  # type: ignore[arg-type]
            **Parametrize("b", tags=["opt-b"], resolve="lock-b"),
        )
    )


def test_default_parametrized_groups(target_adaptor_rule_runner: RuleRunner) -> None:
    target_adaptor_rule_runner.write_files(
        {
            "hello/BUILD": dedent(
                """\
                __defaults__({mock_tgt: dict(**parametrize("a", tags=["from default"]))})
                mock_tgt(
                  tags=["from target"],
                  **parametrize("a"),
                  **parametrize("b", tags=["from b"]),
                )
                """
            ),
        }
    )
    address = Address("hello")
    target_adaptor = target_adaptor_rule_runner.request(
        TargetAdaptor,
        [TargetAdaptorRequest(address, description_of_origin="tests")],
    )
    targets = tuple(Parametrize.expand(address, target_adaptor.kwargs))
    assert targets == (
        (address.parametrize(dict(parametrize="a")), dict(tags=["from target"])),
        (address.parametrize(dict(parametrize="b")), dict(tags=("from b",))),
    )


def test_default_parametrized_groups_with_parametrizations(
    target_adaptor_rule_runner: RuleRunner,
) -> None:
    target_adaptor_rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """
                __defaults__({
                  mock_tgt: dict(
                    **parametrize(
                      "py310-compat",
                      resolve="service-a",
                      tags=[
                        "CPython == 3.9.*",
                        "CPython == 3.10.*",
                      ]
                    ),
                    **parametrize(
                      "py39-compat",
                      resolve=parametrize(
                        "service-b",
                        "service-c",
                        "service-d",
                      ),
                      tags=[
                        "CPython == 3.9.*",
                      ]
                    )
                  )
                })
                mock_tgt()
                """
            ),
        }
    )
    address = Address("src")
    target_adaptor = target_adaptor_rule_runner.request(
        TargetAdaptor,
        [TargetAdaptorRequest(address, description_of_origin="tests")],
    )
    targets = tuple(Parametrize.expand(address, target_adaptor.kwargs))
    assert targets == (
        (
            address.parametrize(dict(parametrize="py310-compat")),
            dict(
                tags=("CPython == 3.9.*", "CPython == 3.10.*"),
                resolve="service-a",
            ),
        ),
        (
            address.parametrize(dict(parametrize="py39-compat", resolve="service-b")),
            dict(tags=("CPython == 3.9.*",), resolve="service-b"),
        ),
        (
            address.parametrize(dict(parametrize="py39-compat", resolve="service-c")),
            dict(tags=("CPython == 3.9.*",), resolve="service-c"),
        ),
        (
            address.parametrize(dict(parametrize="py39-compat", resolve="service-d")),
            dict(tags=("CPython == 3.9.*",), resolve="service-d"),
        ),
    )


def test_augment_target_field_defaults(target_adaptor_rule_runner: RuleRunner) -> None:
    target_adaptor_rule_runner.write_files(
        {
            "BUILD": dedent(
                """
                __defaults__(all=dict(tags=["default-tag"]))
                mock_tgt(
                  sources=["*.added", *mock_tgt.sources.default],
                  tags=["custom-tag", *mock_tgt.tags.default],
                )
                """
            ),
        },
    )
    target_adaptor = target_adaptor_rule_runner.request(
        TargetAdaptor,
        [TargetAdaptorRequest(Address(""), description_of_origin="tests")],
    )
    assert target_adaptor.kwargs["sources"] == ["*.added", "*.mock"]
    assert target_adaptor.kwargs["tags"] == ["custom-tag", "default-tag"]


def test_target_adaptor_not_found(target_adaptor_rule_runner: RuleRunner) -> None:
    with pytest.raises(ExecutionError) as exc:
        target_adaptor_rule_runner.request(
            TargetAdaptor,
            [TargetAdaptorRequest(Address("helloworld"), description_of_origin="tests")],
        )
    assert "Directory \\'helloworld\\' does not contain any BUILD files" in str(exc)

    target_adaptor_rule_runner.write_files({"helloworld/BUILD": "mock_tgt(name='other_tgt')"})
    expected_rx_str = re.escape(
        "The target name ':helloworld' is not defined in the directory helloworld"
    )
    with pytest.raises(ExecutionError, match=expected_rx_str):
        target_adaptor_rule_runner.request(
            TargetAdaptor,
            [TargetAdaptorRequest(Address("helloworld"), description_of_origin="tests")],
        )


def test_build_file_address() -> None:
    rule_runner = RuleRunner(
        rules=[QueryRule(BuildFileAddress, [BuildFileAddressRequest])], target_types=[MockTgt]
    )
    rule_runner.write_files({"helloworld/BUILD.ext": "mock_tgt()"})

    def assert_bfa_resolved(address: Address) -> None:
        expected_bfa = BuildFileAddress(address, "helloworld/BUILD.ext")
        bfa = rule_runner.request(
            BuildFileAddress, [BuildFileAddressRequest(address, description_of_origin="tests")]
        )
        assert bfa == expected_bfa

    assert_bfa_resolved(Address("helloworld"))
    # Generated targets should use their target generator's BUILD file.
    assert_bfa_resolved(Address("helloworld", generated_name="f.txt"))
    assert_bfa_resolved(Address("helloworld", relative_file_path="f.txt"))


def test_build_files_share_globals() -> None:
    """Test that a macro in a prelude can reference another macro in another prelude.

    At some point a change was made to separate the globals/locals dict (unintentional) which has
    the unintended side effect of having the `__globals__` of a macro not contain references to
    every other symbol in every other prelude.
    """

    symbols = run_rule_with_mocks(
        evaluate_preludes,
        rule_args=[
            BuildFileOptions((), prelude_globs=("prelude",)),
            Parser(
                build_root="",
                registered_target_types=RegisteredTargetTypes({}),
                union_membership=UnionMembership({}),
                object_aliases=BuildFileAliases(),
                ignore_unrecognized_symbols=False,
            ),
        ],
        mock_gets=[
            MockGet(
                output_type=DigestContents,
                input_types=(PathGlobs,),
                mock=lambda _: DigestContents(
                    [
                        FileContent(
                            path="/dev/null/prelude1",
                            content=dedent(
                                """\
                                def hello():
                                    pass
                                """
                            ).encode(),
                        ),
                        FileContent(
                            path="/dev/null/prelude2",
                            content=dedent(
                                """\
                                def world():
                                    pass
                                """
                            ).encode(),
                        ),
                    ]
                ),
            ),
        ],
    )
    assert symbols.symbols["hello"].__globals__ is symbols.symbols["world"].__globals__
    assert "world" in symbols.symbols["hello"].__globals__
    assert "hello" in symbols.symbols["world"].__globals__


def test_macro_undefined_symbol_bootstrap() -> None:
    # Tests that an undefined symbol in a macro is ignored while bootstrapping. Ignoring undeclared
    # symbols during parsing is insufficient, because we would need to re-evaluate the preludes after
    # adding each additional undefined symbol to scope.
    rule_runner = RuleRunner(
        rules=[QueryRule(AddressFamily, [AddressFamilyDir])],
        is_bootstrap=True,
    )
    rule_runner.set_options(
        args=("--build-file-prelude-globs=prelude.py",),
    )
    rule_runner.write_files(
        {
            "prelude.py": dedent(
                """
                def uses_undefined():
                    return this_is_undefined()
                """
            ),
            "BUILD": dedent(
                """
                uses_undefined()
                """
            ),
        }
    )

    # Parse the root BUILD file.
    address_family = rule_runner.request(AddressFamily, [AddressFamilyDir("")])
    assert not address_family.name_to_target_adaptors


def test_default_plugin_field_bootstrap() -> None:
    # Tests that an unknown field in `__defaults__` is ignored while bootstrapping.
    rule_runner = RuleRunner(
        rules=[QueryRule(AddressFamily, [AddressFamilyDir])],
        target_types=[MockTgt],
        is_bootstrap=True,
    )
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """
                __defaults__({mock_tgt: dict(presumably_plugin_field="default", tags=["ok"])})
                """
            ),
        }
    )

    # Parse the root BUILD file.
    address_family = rule_runner.request(AddressFamily, [AddressFamilyDir("")])
    assert dict(tags=("ok",)) == dict(address_family.defaults["mock_tgt"])


def test_environment_target_macro_field_value() -> None:
    rule_runner = RuleRunner(
        rules=[QueryRule(AddressFamily, [AddressFamilyDir])],
        target_types=[MockTgt],
        is_bootstrap=True,
    )
    rule_runner.set_options(
        args=("--build-file-prelude-globs=prelude.py",),
    )
    rule_runner.write_files(
        {
            "prelude.py": dedent(
                """
                def tags():
                    return ["foo", "bar"]
                """
            ),
            "BUILD": dedent(
                """
                mock_tgt(name="tgt", tags=tags())
                """
            ),
        }
    )

    # Parse the root BUILD file.
    address_family = rule_runner.request(AddressFamily, [AddressFamilyDir("")])
    tgt = address_family.name_to_target_adaptors["tgt"][1]
    # We're pretending that field values returned from a called macro function doesn't exist during
    # bootstrap. This is to allow the semi-dubios use of macro calls for environment target field
    # values that are not required, and depending on how they are used, it may work to only have
    # those field values set during normal lookup.
    assert not tgt.kwargs
    assert tgt == TargetAdaptor("mock_tgt", "tgt", "BUILD:2")


def test_build_file_env_vars(target_adaptor_rule_runner: RuleRunner) -> None:
    target_adaptor_rule_runner.write_files(
        {
            "BUILD": dedent(
                """
                mock_tgt(
                  description=env("MOCK_DESC"),
                  tags=[
                    env("DEF", "default"),
                    env("TAG", "default"),
                  ]
                )
                """
            ),
        },
    )
    target_adaptor_rule_runner.set_options([], env={"MOCK_DESC": "from env", "TAG": "tag"})
    target_adaptor = target_adaptor_rule_runner.request(
        TargetAdaptor,
        [TargetAdaptorRequest(Address(""), description_of_origin="tests")],
    )
    assert target_adaptor.kwargs["description"] == "from env"
    assert target_adaptor.kwargs["tags"] == ["default", "tag"]


def test_prelude_env_vars(target_adaptor_rule_runner: RuleRunner) -> None:
    target_adaptor_rule_runner.write_files(
        {
            "prelude.py": dedent(
                """
                def macro_val():
                    return env("MACRO_ENV")
                """
            ),
            "BUILD": dedent(
                """
                mock_tgt(
                  description=macro_val(),
                )
                """
            ),
        },
    )
    target_adaptor_rule_runner.set_options(
        args=("--build-file-prelude-globs=prelude.py",),
        env={"MACRO_ENV": "from env"},
    )
    target_adaptor = target_adaptor_rule_runner.request(
        TargetAdaptor,
        [TargetAdaptorRequest(Address(""), description_of_origin="tests")],
    )
    assert target_adaptor.kwargs["description"] == "from env"


def test_invalid_build_file_env_vars(caplog, target_adaptor_rule_runner: RuleRunner) -> None:
    target_adaptor_rule_runner.write_files(
        {
            "src/bad/BUILD": dedent(
                """
                DOES_NOT_WORK = "var_name1"
                DO_THIS_INSTEAD = env("var_name2")

                mock_tgt(description=env(DOES_NOT_WORK), tags=[DO_THIS_INSTEAD])
                """
            ),
        },
    )
    target_adaptor_rule_runner.set_options(
        [], env={"var_name1": "desc from env", "var_name2": "tag-from-env"}
    )
    target_adaptor = target_adaptor_rule_runner.request(
        TargetAdaptor,
        [TargetAdaptorRequest(Address("src/bad"), description_of_origin="tests")],
    )
    assert target_adaptor.kwargs["description"] is None
    assert target_adaptor.kwargs["tags"] == ["tag-from-env"]
    assert_logged(
        caplog,
        [
            (
                logging.WARNING,
                softwrap(
                    """
                    src/bad/BUILD:5: Only constant string values as variable name to `env()` is
                    currently supported. This `env()` call will always result in the default value
                    only.
                    """
                ),
            ),
        ],
    )


def test_build_file_parse_error(target_adaptor_rule_runner: RuleRunner) -> None:
    target_adaptor_rule_runner.write_files(
        {
            "src/bad/BUILD": dedent(
                """\
                mock_tgt(
                  name="foo"
                  tags=[]
                )
                """
            ),
        },
    )
    with pytest.raises(ExecutionError, match='File "src/bad/BUILD", line 3'):
        target_adaptor_rule_runner.request(
            TargetAdaptor,
            [
                TargetAdaptorRequest(
                    Address("src/bad", target_name="foo"), description_of_origin="test"
                )
            ],
        )


def test_build_file_description_of_origin(target_adaptor_rule_runner: RuleRunner) -> None:
    target_adaptor_rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """\
                # Define a target..
                mock_tgt(name="foo")
                """
            ),
        },
    )
    target_adaptor = target_adaptor_rule_runner.request(
        TargetAdaptor,
        [TargetAdaptorRequest(Address("src", target_name="foo"), description_of_origin="test")],
    )
    assert "src/BUILD:2" == target_adaptor.description_of_origin


@pytest.mark.parametrize(
    "filename, contents, expect_failure, expected_message",
    [
        ("BUILD", "data()", False, None),
        (
            "BUILD.qq",
            "data()qq",
            True,
            "Error parsing BUILD file BUILD.qq:1: invalid syntax\n  data()qq\n        ^",
        ),
        (
            "foo/BUILD",
            "data()\nqwe asd",
            True,
            "Error parsing BUILD file foo/BUILD:2: invalid syntax\n  qwe asd\n      ^",
        ),
    ],
)
def test_build_file_syntax_error(filename, contents, expect_failure, expected_message):
    class MockFileContent:
        def __init__(self, path, content):
            self.path = path
            self.content = content

    if expect_failure:
        with pytest.raises(BuildFileSyntaxError) as e:
            BUILDFileEnvVarExtractor.get_env_vars(MockFileContent(filename, contents))

        formatted = str(e.value)

        assert formatted == expected_message

    else:
        BUILDFileEnvVarExtractor.get_env_vars(MockFileContent(filename, contents))
