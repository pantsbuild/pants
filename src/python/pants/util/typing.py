# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
#
import re
import typing

ForwardRefPristine = typing.ForwardRef

_union_exp = r"^([^| \[\]]*)\s*\|\s*([^\[\]]*)$"


def _translate_piped_types_to_union(value: str) -> str:
    # Very naive limited to top-level plain types two-legged unions only.
    return re.sub(_union_exp, r"Union[\1, \2]", value)


def patch_forward_ref() -> None:
    typing.ForwardRef = ForwardRefPatched  # type: ignore[misc]


def restore_forward_ref() -> None:
    typing.ForwardRef = ForwardRefPristine  # type: ignore[misc]


# We are not supposed to subclass this... but we want to support | annotations.
class ForwardRefPatched(typing.ForwardRef, _root=True):  # type: ignore[call-arg, misc]
    def __init__(self, arg, *args, is_class=False, **kwargs):
        unionised_arg = _translate_piped_types_to_union(arg)
        if unionised_arg != arg:
            is_class = True
        super().__init__(unionised_arg, *args, is_class=is_class, **kwargs)

    def _evaluate(self, globalns, localns, recursive_guard):
        if self.__forward_is_class__ and globalns and "Union" not in globalns:
            globalns["Union"] = typing.Union
        return super()._evaluate(globalns, localns, recursive_guard)
