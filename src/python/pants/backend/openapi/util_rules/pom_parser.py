# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass

from pants.engine.fs import Digest, DigestContents
from pants.engine.rules import Get, collect_rules, rule
from pants.jvm.resolve.coordinate import Coordinate


@dataclass(frozen=True)
class AnalysePomRequest:
    pom_digest: Digest


@dataclass(frozen=True)
class PomReport:
    dependencies: tuple[Coordinate, ...]


_MAVEN_NAMESPACE = "http://maven.apache.org/POM/4.0.0"
_MAVEN_NAMESPACE_MAP = {"mvn": _MAVEN_NAMESPACE}


@rule(desc="Analysing Maven POM file")
async def analyse_pom(request: AnalysePomRequest) -> PomReport:
    contents = await Get(DigestContents, Digest, request.pom_digest)
    assert len(contents) == 1

    root = ET.fromstring(contents[0].content)

    def maybe_lookup_property(txt: str | None) -> str | None:
        if not txt:
            return None

        if txt.startswith("${") and txt.endswith("}"):
            prop = txt[2:-1]
            prop_value = root.findtext(
                f".//mvn:properties/mvn:{prop}", namespaces=_MAVEN_NAMESPACE_MAP
            )
            if prop_value:
                return prop_value
        return txt

    coordinates = []
    for dep in root.findall(".//mvn:dependency", namespaces=_MAVEN_NAMESPACE_MAP):
        scope = maybe_lookup_property(dep.findtext("mvn:scope", namespaces=_MAVEN_NAMESPACE_MAP))
        if scope and scope == "test":
            continue

        coord_dict = {
            "artifact": maybe_lookup_property(
                dep.findtext("mvn:artifactId", namespaces=_MAVEN_NAMESPACE_MAP)
            ),
            "group": maybe_lookup_property(
                dep.findtext("mvn:groupId", namespaces=_MAVEN_NAMESPACE_MAP)
            ),
            "version": maybe_lookup_property(
                dep.findtext("mvn:version", namespaces=_MAVEN_NAMESPACE_MAP)
            ),
            "packaging": maybe_lookup_property(
                dep.findtext("mvn:packaging", default="jar", namespaces=_MAVEN_NAMESPACE_MAP)
            ),
            "classifier": maybe_lookup_property(
                dep.findtext("mvn:classifier", namespaces=_MAVEN_NAMESPACE_MAP)
            ),
        }
        coordinates.append(Coordinate.from_json_dict(coord_dict))

    return PomReport(tuple(coordinates))


def rules():
    return collect_rules()
