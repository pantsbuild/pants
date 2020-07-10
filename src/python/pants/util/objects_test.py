# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent
from typing import Any, Iterable, List, Optional, Union

from pants.util.objects import get_docstring, get_docstring_summary, pretty_print_type_hint


def test_get_docstring() -> None:
    class SingleLineDocstring:
        """Hello."""

    assert get_docstring_summary(SingleLineDocstring) == "Hello."
    assert get_docstring(SingleLineDocstring) == "Hello."
    assert get_docstring(SingleLineDocstring, flatten=True) == "Hello."

    class MultilineDocstring:
        """Hello.

        Extra description.
        """

    assert get_docstring_summary(MultilineDocstring) == "Hello."
    assert get_docstring(MultilineDocstring) == dedent(
        """\
        Hello.

        Extra description."""
    )
    assert get_docstring(MultilineDocstring, flatten=True) == "Hello. Extra description."

    class NoDocstring:
        pass

    assert get_docstring_summary(NoDocstring) is None
    assert get_docstring(NoDocstring) is None
    assert get_docstring(NoDocstring, flatten=True) is None

    long_summary = (
        "This is all one sentence, it's just really really really long so it stretches to a "
        "whole new line."
    )

    class MultilineSummary:
        """This is all one sentence, it's just really really really long so it stretches to a whole
        new line."""

    assert get_docstring_summary(MultilineSummary) == long_summary
    assert get_docstring(MultilineSummary) == dedent(
        """\
        This is all one sentence, it's just really really really long so it stretches to a whole
        new line."""
    )
    assert get_docstring(MultilineSummary, flatten=True) == long_summary

    class MultilineSummaryWithDetails:
        """This is all one sentence, it's just really really really long so it stretches to a whole
        new line.

        We also have some extra detail.

            * l1
            * l2
        """

    assert get_docstring_summary(MultilineSummaryWithDetails) == long_summary
    assert get_docstring(MultilineSummaryWithDetails) == dedent(
        """\
        This is all one sentence, it's just really really really long so it stretches to a whole
        new line.

        We also have some extra detail.

            * l1
            * l2"""
    )
    assert (
        get_docstring(MultilineSummaryWithDetails, flatten=True)
        == f"{long_summary} We also have some extra detail. * l1 * l2"
    )

    class SneakyDocstring:
        """Hello 😀!\n\nSneaky."""

    assert get_docstring_summary(SneakyDocstring) == "Hello 😀!"
    assert get_docstring(SneakyDocstring) == dedent(
        """\
        Hello 😀!

        Sneaky."""
    )
    assert get_docstring(SneakyDocstring, flatten=True) == "Hello 😀! Sneaky."


def test_pretty_print_type_hint() -> None:
    assert pretty_print_type_hint(str) == "str"
    assert pretty_print_type_hint(int) == "int"
    assert pretty_print_type_hint(None) == "None"

    class ExampleCls:
        pass

    assert pretty_print_type_hint(ExampleCls) == "ExampleCls"

    # Transform Unions to use `|`
    assert pretty_print_type_hint(Union[int, float]) == "int | float"
    assert pretty_print_type_hint(Optional[int]) == "int | None"
    # NB: `Iterable[List[ExampleCls]]` will use the full module name for `ExampleCls`. We can't
    # easily control that because it comes from the __repr__ implementation for `typing.Iterable`.
    example_cls_repr = (
        f"{__name__}.{test_pretty_print_type_hint.__name__}.<locals>.{ExampleCls.__name__}"
    )
    assert (
        pretty_print_type_hint(Union[Iterable[List[ExampleCls]], Optional[float], Any])
        == f"Iterable[List[{example_cls_repr}]] | float | None | Any"
    )


def test_get_docstring_fallback_to_parents() -> None:
    class Grandparent:
        """Grandparent."""

    class ParentWithDocstring(Grandparent):
        """Parent."""

    class ParentWithoutDocstring(Grandparent):
        pass

    class ChildWithParentDocstring(ParentWithDocstring):
        pass

    class ChildWithGrandparentDocstring(ParentWithoutDocstring):
        pass

    class ChildWithDocstring(ParentWithDocstring):
        """Child."""

    assert get_docstring(ChildWithParentDocstring, fallback_to_ancestors=True) == "Parent."
    assert (
        get_docstring(ChildWithGrandparentDocstring, fallback_to_ancestors=True) == "Grandparent."
    )
    assert get_docstring(ChildWithDocstring, fallback_to_ancestors=True) == "Child."

    # `object` is the "cosmic" superclass.
    class FallbackToObject:
        pass

    assert (
        get_docstring(FallbackToObject, fallback_to_ancestors=True, ignored_ancestors=[object])
        is None
    )
    assert (
        get_docstring(FallbackToObject, fallback_to_ancestors=True, ignored_ancestors=[])
        == object.__doc__
    )
