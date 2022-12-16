# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Callable, Iterable, TypeVar

from typing_extensions import Concatenate, ParamSpec

from pants.engine.rules import Rule, collect_rules
from pants.util.memo import memoized

P = ParamSpec("P")
T = TypeVar("T")


class RuleRegistry:
    """Helper class to permit selective registration of rules."""

    _rules: list

    def __init__(self):
        self._rules = []

    def build(self) -> Iterable[Rule]:
        return collect_rules({_rule.__name__: _rule for _rule in self._rules})

    def __call__(
        self, rule_spec: Callable[[Callable[P, T]], Callable[P, T]], *, predicate: bool = True
    ) -> Callable[[Callable[P, T]], Callable[P, T]]:
        """Register the decorated function as a rule. The rule is not provided to the engine until
        `build` is called.

        * `rule_spec` should be a decorator from `pants.engine.rules`
        *`predicate` is an optional boolean that allows selective registration of rules. If
         `predicate` is falsey, the rule is not registered.
        """

        def decorated(f: Callable[P, T]) -> Callable[P, T]:
            if predicate:
                rule_spec(f)
                self._rules.append(f)
            return f

        return decorated


def rule_builder(f: Callable[Concatenate[RuleRegistry, P], None]) -> Callable[P, Iterable[Rule]]:
    """Turns the decorated function into a Rule Builder: a callable that is provided with a
    `RuleRegistry` as its first parameter, which can be used to create new rules inside a function,
    which can be useful when rules need to be created selectively.

    Rule Builders must return `None`, and once the function returns, the `RuleRegistry` is built
    and discarded. When decorated, a `rule_builder` function will return an iterable of `Rule`s
    for use in a module's `rules` function.

    Example:
    ```
    @rule_builder
    def some_rules(register: RuleRegistry, param: int) -> None:

        @register(rule())
        async def a_rule(request: RequestType) -> ReturnType:
            return await Get(ReturnType, ReturnTypeRequest(request.data))

        # Rules can be selectively discarded, using the `predicate` parameter
        @register(rule(), predicate=(param == 57))
        async def rule_that_is_discarded(request: RequestType) -> ReturnType:
            return await Get(ReturnType, ReturnTypeRequest(request.data))

    def rules():
        return [
            *some_rules(57),
        ]
    ```
    """

    @memoized
    def new_function(*a: P.args, **k: P.kwargs) -> Iterable[Rule]:
        builder = RuleRegistry()
        f(builder, *a, **k)
        return builder.build()

    new_function.__name__ = f.__name__
    return new_function
