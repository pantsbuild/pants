# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from types import CoroutineType, GeneratorType
from typing import (
    Any,
    Callable,
    List,
    Optional,
    Sequence,
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
    get_type_hints,
)

from colors import blue, cyan, green, magenta, red

from pants.engine.goal import GoalSubsystem
from pants.engine.internals.addressable import addressable_sequence
from pants.engine.internals.native import Native
from pants.engine.internals.parser import SymbolTable
from pants.engine.internals.scheduler import Scheduler
from pants.engine.internals.struct import Struct
from pants.engine.selectors import Get
from pants.engine.unions import UnionMembership
from pants.option.global_options import DEFAULT_EXECUTION_OPTIONS
from pants.option.option_value_container import OptionValueContainer
from pants.option.ranked_value import Rank, RankedValue, Value
from pants.subsystem.subsystem import Subsystem
from pants.util.objects import SubclassesOf


# TODO(#6742): Improve the type signature by using generics and type vars. `mock` should be
#  `Callable[[SubjectType], ProductType]`.
@dataclass(frozen=True)
class MockGet:
    product_type: Type
    subject_type: Type
    mock: Callable[[Any], Any]


def _create_scoped_options(
    default_rank: Rank, **options: Union[RankedValue, Value]
) -> OptionValueContainer:
    scoped_options = OptionValueContainer()
    for key, value in options.items():
        if not isinstance(value, RankedValue):
            value = RankedValue(default_rank, value)
        setattr(scoped_options, key, value)
    return scoped_options


GS = TypeVar("GS", bound=GoalSubsystem)


def create_goal_subsystem(
    goal_subsystem_type: Type[GS],
    default_rank: Rank = Rank.NONE,
    **options: Union[RankedValue, Value],
) -> GS:
    """Creates a new goal subsystem instance populated with the given option values.

    :param goal_subsystem_type: The `GoalSubsystem` type to create.
    :param default_rank: The rank to assign any raw option values passed.
    :param options: The option values to populate the new goal subsystem instance with.
    """
    return goal_subsystem_type(
        scope=goal_subsystem_type.name,
        scoped_options=_create_scoped_options(default_rank, **options),
    )


SS = TypeVar("SS", bound=Subsystem)


def create_subsystem(
    subsystem_type: Type[SS], default_rank: Rank = Rank.NONE, **options: Union[RankedValue, Value],
) -> SS:
    """Creates a new subsystem instance populated with the given option values.

    :param subsystem_type: The `Subsystem` type to create.
    :param default_rank: The rank to assign any raw option values passed.
    :param options: The option values to populate the new subsystem instance with.
    """
    options_scope = cast(str, subsystem_type.options_scope)
    return subsystem_type(
        scope=options_scope, scoped_options=_create_scoped_options(default_rank, **options),
    )


def run_rule(
    rule,
    *,
    rule_args: Optional[Sequence[Any]] = None,
    mock_gets: Optional[Sequence[MockGet]] = None,
    union_membership: Optional[UnionMembership] = None,
):
    """A test helper function that runs an @rule with a set of arguments and mocked Get providers.

    An @rule named `my_rule` that takes one argument and makes no `Get` requests can be invoked
    like so (although you could also just invoke it directly):

    ```
    return_value = run_rule(my_rule, rule_args=[arg1])
    ```

    In the case of an @rule that makes Get requests, things get more interesting: the
    `mock_gets` argument must be provided as a sequence of `MockGet`s. Each MockGet takes the Product
    and Subject type, along with a one-argument function that takes a subject value and returns a
    product value.

    So in the case of an @rule named `my_co_rule` that takes one argument and makes Get requests
    for a product type `Listing` with subject type `Dir`, the invoke might look like:

    ```
    return_value = run_rule(
      my_co_rule,
      rule_args=[arg1],
      mock_gets=[
        MockGet(
          product_type=Listing,
          subject_type=Dir,
          mock=lambda dir_subject: Listing(..),
        ),
      ],
    )
    ```

    If any of the @rule's Get requests involve union members, you should pass a `UnionMembership`
    mapping the union base to any union members you'd like to test. For example, if your rule has
    `await Get[TestResult](TargetAdaptor, target_adaptor)`, you may pass
    `UnionMembership({TargetAdaptor: PythonTestsTargetAdaptor})` to this function.

    :returns: The return value of the completed @rule.
    """

    task_rule = getattr(rule, "rule", None)
    if task_rule is None:
        raise TypeError(f"Expected to receive a decorated `@rule`; got: {rule}")

    if rule_args is not None and len(rule_args) != len(task_rule.input_selectors):
        raise ValueError(
            "Rule expected to receive arguments of the form: {}; got: {}".format(
                task_rule.input_selectors, rule_args
            )
        )

    if mock_gets is not None and len(mock_gets) != len(task_rule.input_gets):
        raise ValueError(
            "Rule expected to receive Get providers for {}; got: {}".format(
                task_rule.input_gets, mock_gets
            )
        )

    res = rule(*(rule_args or ()))
    if not isinstance(res, (CoroutineType, GeneratorType)):
        return res

    def get(product, subject):
        provider = next(
            (
                mock_get.mock
                for mock_get in mock_gets
                if mock_get.product_type == product
                and (
                    mock_get.subject_type == type(subject)
                    or (
                        union_membership
                        and union_membership.is_member(mock_get.subject_type, subject)
                    )
                )
            ),
            None,
        )
        if provider is None:
            raise AssertionError(
                "Rule requested: Get{}, which cannot be satisfied.".format(
                    (product, type(subject), subject)
                )
            )
        return provider(subject)

    rule_coroutine = res
    rule_input = None
    while True:
        try:
            res = rule_coroutine.send(rule_input)
            if Get.isinstance(res):
                rule_input = get(res.product_type, res.subject)
            elif type(res) in (tuple, list):
                rule_input = [get(g.product_type, g.subject) for g in res]
            else:
                return res
        except StopIteration as e:
            if e.args:
                return e.value


def init_native():
    """Return the `Native` instance."""
    return Native()


def create_scheduler(rules, union_rules=None, validate=True, native=None):
    """Create a Scheduler."""
    native = native or init_native()
    return Scheduler(
        native=native,
        ignore_patterns=[],
        use_gitignore=False,
        build_root=str(Path.cwd()),
        local_store_dir="./.pants.d/lmdb_store",
        local_execution_root_dir="./.pants.d",
        named_caches_dir="./.pants.d/named_caches",
        rules=rules,
        union_rules=union_rules,
        execution_options=DEFAULT_EXECUTION_OPTIONS,
        validate=validate,
    )


class Target(Struct):
    def __init__(self, name=None, configurations=None, **kwargs):
        super().__init__(name=name, **kwargs)
        self.configurations = configurations

    @addressable_sequence(SubclassesOf(Struct))
    def configurations(self):
        pass


TARGET_TABLE = SymbolTable({"struct": Struct, "target": Target})


def assert_equal_with_printing(
    test_case, expected, actual, uniform_formatter: Optional[Callable[[str], str]] = None
):
    """Asserts equality, but also prints the values so they can be compared on failure.

    Usage:

       class FooTest(unittest.TestCase):
         assert_equal_with_printing = assert_equal_with_printing

         def test_foo(self):
           self.assert_equal_with_printing("a", "b")
    """
    str_actual = str(actual)
    print("Expected:")
    print(expected)
    print("Actual:")
    print(str_actual)

    if uniform_formatter is not None:
        expected = uniform_formatter(expected)
        str_actual = uniform_formatter(str_actual)

    test_case.assertEqual(expected, str_actual)


def remove_locations_from_traceback(trace: str) -> str:
    location_pattern = re.compile(r'"/.*", line \d+')
    address_pattern = re.compile(r"0x[0-9a-f]+")
    new_trace = location_pattern.sub("LOCATION-INFO", trace)
    new_trace = address_pattern.sub("0xEEEEEEEEE", new_trace)
    return new_trace


class MockConsole:
    """An implementation of pants.engine.console.Console which captures output."""

    def __init__(self, use_colors=True):
        self.stdout = StringIO()
        self.stderr = StringIO()
        self._use_colors = use_colors

    def write_stdout(self, payload):
        self.stdout.write(payload)

    def write_stderr(self, payload):
        self.stderr.write(payload)

    def print_stdout(self, payload):
        print(payload, file=self.stdout)

    def print_stderr(self, payload):
        print(payload, file=self.stderr)

    def _safe_color(self, text: str, color: Callable[[str], str]) -> str:
        return color(text) if self._use_colors else text

    def blue(self, text: str) -> str:
        return self._safe_color(text, blue)

    def cyan(self, text: str) -> str:
        return self._safe_color(text, cyan)

    def green(self, text: str) -> str:
        return self._safe_color(text, green)

    def magenta(self, text: str) -> str:
        return self._safe_color(text, magenta)

    def red(self, text: str) -> str:
        return self._safe_color(text, red)


def fmt_rust_function(func: Callable) -> str:
    """Generate the str for a Rust Function, which is how Rust refers to `@rule`s.

    This is useful when comparing strings against engine error messages. See
    https://github.com/pantsbuild/pants/blob/5b97905443836b71dfa77cefc7cbc1735c7457cb/src/rust/engine/src/core.rs#L164.
    """
    return f"{func.__module__}:{func.__code__.co_firstlineno}:{func.__name__}"


def fmt_rule(rule: Callable, *, gets: Optional[List[Tuple[str, str]]] = None) -> str:
    """Generate the str that the engine will use for the rule.

    This is useful when comparing strings against engine error messages.
    """
    type_hints = get_type_hints(rule)
    product = type_hints.pop("return").__name__
    params = ", ".join(t.__name__ for t in type_hints.values())
    gets_str = ""
    if gets:
        get_members = ", ".join(
            f"Get[{product_subject_pair[0]}]({product_subject_pair[1]})"
            for product_subject_pair in gets
        )
        gets_str = f", gets=[{get_members}]"
    return f"@rule({fmt_rust_function(rule)}({params}) -> {product}{gets_str})"
