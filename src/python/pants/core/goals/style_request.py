# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABCMeta
from dataclasses import dataclass
from typing import ClassVar, Generic, Iterable, Optional, Type, TypeVar

from pants.engine.collection import Collection
from pants.engine.fs import Snapshot
from pants.engine.target import FieldSet
from pants.util.meta import frozen_after_init

_FS = TypeVar("_FS", bound=FieldSet)


@frozen_after_init
@dataclass(unsafe_hash=True)
class StyleRequest(Generic[_FS], metaclass=ABCMeta):
    """A request to style or lint a collection of `FieldSet`s.

    Should be subclassed for a particular style engine in order to support autoformatting or
    linting.
    """

    field_set_type: ClassVar[Type[_FS]]

    field_sets: Collection[_FS]
    prior_formatter_result: Optional[Snapshot] = None

    def __init__(
        self,
        field_sets: Iterable[_FS],
        *,
        prior_formatter_result: Optional[Snapshot] = None,
    ) -> None:
        self.field_sets = Collection[_FS](field_sets)
        self.prior_formatter_result = prior_formatter_result
