# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass

from pants.backend.python.dependency_inference.parse_python_dependencies import get_scripts_digest
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import InterpreterConstraintsField
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex_environment import PythonExecutable
from pants.base.specs import FileGlobSpec, RawSpecs
from pants.engine.fs import AddPrefix, Digest, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    HydratedSources,
    HydrateSourcesRequest,
    SourcesField,
    Target,
    Targets,
)
from pants.util.frozendict import FrozenDict


@dataclass(frozen=True)
class DjangoAppsRequest:
    pass


@dataclass(frozen=True)
class DjangoApps:
    label_to_name: FrozenDict[str, str]

    def add_from_json(self, json_bytes: bytes) -> "DjangoApps":
        apps = dict(self.label_to_name, **json.loads(json_bytes.decode()))
        return DjangoApps(FrozenDict(sorted(apps.items())))

    def to_json(self) -> bytes:
        return json.dumps(dict(self.label_to_name), sort_keys=True).encode()


@rule
async def detect_django_apps(
    _: DjangoAppsRequest,
    python_setup: PythonSetup,
) -> DjangoApps:
    # A Django app has a "name" - the full import path to the app ("path.to.myapp"),
    # and a "label" - a short name, usually the last segment of the import path ("myapp").
    #
    # An app provides this information via a subclass of AppConfig, living in a
    # file named apps.py.  Django loads this information into an app registry at runtime.
    #
    # Some parts of Django, notably migrations, use the label to reference apps. So to do custom
    # Django dep inference, we need to know the label -> name mapping.
    #
    # The only truly correct way to enumerate Django apps is to run the Django app registry code.
    # However we can't do this until after dep inference has completed, and even then it would be
    # complicated: we wouldn't know which settings.py to use, or whether it's safe to run Django
    # against that settings.py. Instead, we do this statically via parsing the apps.py file.
    #
    # NB: Legacy Django apps may not have an apps.py, in which case the label is assumed to be
    #  the name of the app dir, but the recommendation for many years has been to have it, and
    #  the Django startapp tool creates it for you. If an app does not have such an apps.py,
    #  then we won't be able to infer deps on that app unless we find other ways of detecting it.
    #  We should only do that if that case turns out to be common, and for some reason users can't
    #  simply create an apps.py to fix the issue.
    #
    # NB: Right now we only detect first-party apps in repo. We assume that third-party apps will
    #  be dep-inferred as a whole via the full package path in settings.py anyway.
    #  In the future we may find a way to map third-party apps here as well.
    django_apps = DjangoApps(FrozenDict())
    targets = await Get(
        Targets,
        RawSpecs,
        RawSpecs.create(
            specs=[FileGlobSpec("**/apps.py")], description_of_origin="Django app detection"
        ),
    )
    if not targets:
        return django_apps

    script_digest = await get_scripts_digest(
        "pants.backend.python.framework.django.scripts", ["app_detector.py"]
    )
    apps_sandbox_prefix = "_apps_to_detect"

    # Partition by ICs, so we can run the detector on the appropriate interpreter.
    ics_to_tgts: dict[InterpreterConstraints, list[Target]] = defaultdict(list)
    for tgt in targets:
        ics = InterpreterConstraints(
            tgt[InterpreterConstraintsField].value_or_global_default(python_setup)
        )
        ics_to_tgts[ics].append(tgt)

    for ics, tgts in ics_to_tgts.items():
        sources = await MultiGet(  # noqa: PNT30: requires triage
            [Get(HydratedSources, HydrateSourcesRequest(tgt[SourcesField])) for tgt in tgts]
        )
        apps_digest = await Get(  # noqa: PNT30: requires triage
            Digest, MergeDigests([src.snapshot.digest for src in sources])
        )
        prefixed_apps_digest = await Get(  # noqa: PNT30: requires triage
            Digest, AddPrefix(apps_digest, apps_sandbox_prefix)
        )

        input_digest = await Get(  # noqa: PNT30: requires triage
            Digest, MergeDigests([prefixed_apps_digest, script_digest])
        )
        python_interpreter = await Get(  # noqa: PNT30: requires triage
            PythonExecutable, InterpreterConstraints, ics
        )

        process_result = await Get(  # noqa: PNT30: requires triage
            ProcessResult,
            Process(
                argv=[
                    python_interpreter.path,
                    "pants/backend/python/framework/django/scripts/app_detector.py",
                    apps_sandbox_prefix,
                ],
                input_digest=input_digest,
                description="Detect Django apps",
            ),
        )
        django_apps = django_apps.add_from_json(process_result.stdout or b"{}")
    return django_apps


def rules():
    return [
        *collect_rules(),
    ]
