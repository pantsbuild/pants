from typing import Any, cast

from dataclasses import dataclass

from pants.util.frozendict import FrozenDict


@dataclass(frozen=True)
class TemplatedBackendConfig:
    template: str
    kwargs: FrozenDict[str, Any]

    @classmethod
    def from_dict(cls, d: Any):
        d = dict(d)
        template = d.pop('template', None)
        if not template:
            raise ValueError(f'"template" is a required key for a backend template')
        return cls(template=cast(str, template), kwargs=FrozenDict(d))
