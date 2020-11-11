# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import operator
from typing import Callable, Iterable, Sequence, Tuple, TypeVar

_T = TypeVar("_T")
Filter = Callable[[_T], bool]


def _extract_modifier(modified_param: str) -> Tuple[Callable[[bool], bool], str]:
    if modified_param.startswith("-"):
        return operator.not_, modified_param[1:]
    identity_func = lambda x: x
    return identity_func, modified_param[1:] if modified_param.startswith("+") else modified_param


def create_filter(predicate_param: str, predicate_factory: Callable[[str], Filter]) -> Filter:
    """Create a filter function from a string parameter.

    :param predicate_param: Create a filter for this param string. Each string is a
                            comma-separated list of arguments to the predicate_factory.
                            If the entire comma-separated list is prefixed by a '-' then the
                            sense of the resulting filter is inverted.
    :param predicate_factory: A function that takes a parameter and returns a predicate, i.e., a
                              function that takes a single parameter (of whatever type the filter
                              operates on) and returns a boolean.
    :return: A filter function of one argument that is the logical OR of the predicates for each of
             the comma-separated arguments. If the comma-separated list was prefixed by a '-',
             the sense of the filter is inverted.

    :API: public
    """
    modifier, param = _extract_modifier(predicate_param)
    predicates = [predicate_factory(p) for p in param.split(",")]

    def filt(x: _T) -> bool:
        return modifier(any(pred(x) for pred in predicates))

    return filt


def create_filters(
    predicate_params: Iterable[str], predicate_factory: Callable[[str], Filter]
) -> Sequence[Filter]:
    """Create filter functions from a list of string parameters.

    :param predicate_params: A list of predicate_param arguments as in `create_filter`.
    :param predicate_factory: As in `create_filter`.

    :API: public
    """
    filters = []
    for predicate_param in predicate_params:
        filters.append(create_filter(predicate_param, predicate_factory))
    return filters


def and_filters(filters: Iterable[Filter]) -> Filter:
    """Returns a single filter that short-circuit ANDs the specified filters.

    :API: public
    """

    def combined_filter(x: _T) -> bool:
        for filt in filters:
            if not filt(x):
                return False
        return True

    return combined_filter
