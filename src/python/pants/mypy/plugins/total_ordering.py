# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# See: https://mypy.readthedocs.io/en/latest/extending_mypy.html#high-level-overview

from typing import Callable, Optional, Type

from mypy.nodes import ARG_POS, Argument, TypeInfo, Var
from mypy.plugin import ClassDefContext, Plugin
from mypy.plugins.common import add_method


class TotalOrderingPlugin(Plugin):
    @staticmethod
    def adjust_class_def(class_def_context: ClassDefContext) -> None:
        # This MyPy plugin inserts method type stubs for the "missing" ordering methods the
        # @total_ordering class decorator will fill in dynamically.

        api = class_def_context.api
        ordering_other_type = api.named_type("__builtins__.object")
        ordering_return_type = api.named_type("__builtins__.bool")
        args = [
            Argument(
                variable=Var(name="other", type=ordering_other_type),
                type_annotation=ordering_other_type,
                initializer=None,
                kind=ARG_POS,
            )
        ]

        type_info: TypeInfo = class_def_context.cls.info
        for ordering_method_name in "__lt__", "__le__", "__gt__", "__ge__":
            existing_method = type_info.get(ordering_method_name)
            if existing_method is None:
                add_method(
                    ctx=class_def_context,
                    name=ordering_method_name,
                    args=args,
                    return_type=ordering_return_type,
                )

    def get_class_decorator_hook(
        self, fullname: str
    ) -> Optional[Callable[[ClassDefContext], None]]:
        return self.adjust_class_def if fullname == "functools.total_ordering" else None


def plugin(_version: str) -> Type[Plugin]:
    return TotalOrderingPlugin
