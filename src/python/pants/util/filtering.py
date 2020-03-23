# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import operator

_identity = lambda x: x


def _extract_modifier(modified_param):
    if modified_param.startswith("+"):
        return _identity, modified_param[1:]
    elif modified_param.startswith("-"):
        return operator.not_, modified_param[1:]
    else:
        return _identity, modified_param


def create_filters(predicate_params, predicate_factory):
    """Create filter functions from a list of string parameters.

    :param predicate_params: A list of predicate_param arguments as in `create_filter`.
    :param predicate_factory: As in `create_filter`.
    """
    filters = []
    for predicate_param in predicate_params:
        filters.append(create_filter(predicate_param, predicate_factory))
    return filters


def create_filter(predicate_param, predicate_factory):
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
    """
    # NOTE: Do not inline this into create_filters above. A separate function is necessary
    # in order to capture the different closure on each invocation.
    modifier, param = _extract_modifier(predicate_param)
    predicates = [predicate_factory(p) for p in param.split(",")]

    def filt(x):
        return modifier(any(pred(x) for pred in predicates))

    return filt


def wrap_filters(filters):
    """Returns a single filter that short-circuit ANDs the specified filters.

    :API: public
    """

    def combined_filter(x):
        for filt in filters:
            if not filt(x):
                return False
        return True

    return combined_filter
