# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Any

from pants.util.strutil import softwrap


def parse_expression(
    val: str, acceptable_types: type | tuple[type, ...], name: str | None = None
) -> Any:
    """Attempts to parse the given `val` as a python expression of the specified `acceptable_types`.

    :param val: A string containing a python expression.
    :param acceptable_types: The acceptable types of the parsed object.
    :param name: An optional logical name for the value being parsed; ie if the literal val
                        represents a person's age, 'age'.
    :raises: If `val` is not a valid python literal expression or it is but evaluates to an object
             that is not a an instance of one of the `acceptable_types`.
    """

    def format_type(typ):
        return typ.__name__

    if not isinstance(val, str):
        raise ValueError(
            f"The raw `val` is not a str.  Given {val} of type {format_type(type(val))}."
        )

    def get_name():
        return repr(name) if name else "value"

    def format_raw_value():
        lines = val.splitlines()
        for line_number in range(0, len(lines)):
            lines[line_number] = "{line_number:{width}}: {line}".format(
                line_number=line_number + 1, line=lines[line_number], width=len(str(len(lines)))
            )
        return "\n".join(lines)

    try:
        parsed_value = eval(val)
    except Exception as e:
        raise ValueError(
            softwrap(
                f"""
                The {get_name()} cannot be evaluated as a literal expression: {e!r}
                Given raw value:
                  {format_raw_value()}
                """
            )
        )

    if not isinstance(parsed_value, acceptable_types):

        def iter_types(types):
            if isinstance(types, type):
                yield types
            elif isinstance(types, tuple):
                for item in types:
                    yield from iter_types(item)
            else:
                raise ValueError(
                    f"The given acceptable_types is not a valid type (tuple): {acceptable_types}"
                )

        expected_types = ", ".join(format_type(t) for t in iter_types(acceptable_types))
        raise ValueError(
            softwrap(
                f"""
                The {get_name()} is not of the expected type(s): {expected_types}:
                Given the following raw value that evaluated to type {format_type(type(parsed_value))}:
                  {format_raw_value()}
                """
            )
        )
    return parsed_value
