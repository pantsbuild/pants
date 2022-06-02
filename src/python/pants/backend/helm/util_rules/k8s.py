# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum, unique
from typing import Any, cast

import yaml

from pants.engine.collection import Collection
from pants.engine.fs import Digest, DigestContents, DigestSubset, PathGlobs
from pants.engine.rules import Get, collect_rules, rule
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


@unique
class StandardKind(Enum):
    """The kind of Kubernetes resource."""

    CONFIG_MAP = "ConfigMap"
    CRON_JOB = "CronJob"
    DAEMON_SET = "DaemonSet"
    DEPLOYMENT = "Deployment"
    INGRESS = "Ingress"
    PERSISTENT_VOLUME = "PersistentVolume"
    PERSISTENT_VOLUME_CLAIM = "PersistentVolumeClaim"
    POD = "Pod"
    JOB = "Job"
    REPLICA_SET = "ReplicaSet"
    SECRET = "Secret"
    SERVICE = "Service"
    STATEFUL_SET = "StatefulSet"


_DEFAULT_CONTAINER_TAG = "latest"


@dataclass(frozen=True)
class CustomResourceKind:
    value: str


@dataclass(frozen=True)
class ImageRef:
    registry: str | None
    repository: str
    tag: str = _DEFAULT_CONTAINER_TAG

    @classmethod
    def parse(cls, image_ref: str) -> ImageRef:
        registry = None
        tag = _DEFAULT_CONTAINER_TAG

        addr_and_tag = image_ref.split(":")
        if len(addr_and_tag) > 1:
            tag = addr_and_tag[1]

        slash_idx = addr_and_tag[0].find("/")
        if slash_idx >= 0:
            registry = addr_and_tag[0][:slash_idx]
            repo = addr_and_tag[0][(slash_idx + 1) :]
        else:
            repo = addr_and_tag[0]

        return cls(registry=registry, repository=repo, tag=tag)

    def __str__(self) -> str:
        return f"{self.registry}/{self.repository}:{self.tag}"


@dataclass(frozen=True)
class KubeManifest:
    api_version: str
    kind: StandardKind | CustomResourceKind
    container_images: tuple[ImageRef, ...]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> KubeManifest:
        std_kind: StandardKind | None = None
        try:
            std_kind = StandardKind(d["kind"])
        except ValueError:
            custom_kind = CustomResourceKind(d["kind"])

        container_images: list[ImageRef] = []
        if std_kind:
            container_images = KubeManifest._extract_container_images(std_kind, d["spec"])

        return cls(
            api_version=d["apiVersion"],
            kind=std_kind or custom_kind,
            container_images=tuple(container_images),
        )

    @staticmethod
    def _extract_container_images(kind: StandardKind, spec: dict[str, Any]) -> list[ImageRef]:
        def safe_get(path: list[str]) -> Any | None:
            lookup_from = spec
            result = None
            for path_elem in path:
                result = lookup_from.get(path_elem)
                lookup_from = result or {}
                if not result:
                    break
            return result

        def get_containers(spec_path: list[str]) -> list[dict[str, Any]]:
            cs = safe_get([*spec_path, "containers"]) or []
            cs.extend(safe_get([*spec_path, "initContainers"]) or [])
            return cs

        containers = []
        if kind == StandardKind.CRON_JOB:
            containers = get_containers(["jobTemplate", "spec", "template", "spec"])
        elif kind == StandardKind.DAEMON_SET:
            containers = get_containers(["template", "spec"])
        elif kind == StandardKind.DEPLOYMENT:
            containers = get_containers(["template", "spec"])
        elif kind == StandardKind.JOB:
            containers = get_containers(["template", "spec"])
        elif kind == StandardKind.POD:
            containers = get_containers([])
        elif kind == StandardKind.REPLICA_SET:
            containers = get_containers(["template", "spec"])
        elif kind == StandardKind.STATEFUL_SET:
            containers = get_containers(["template", "spec"])

        return [ImageRef.parse(cast(str, container["image"])) for container in containers]


class KubeManifests(Collection[KubeManifest]):
    pass


@dataclass(frozen=True)
class ParseKubeManifests:
    digest: Digest
    description_of_origin: str


@rule
async def parse_kubernetes_manifests(request: ParseKubeManifests) -> KubeManifests:
    yaml_subset = await Get(
        Digest, DigestSubset(request.digest, PathGlobs(["**/*.yaml", "**/*.yml"]))
    )
    digest_contents = await Get(DigestContents, Digest, yaml_subset)

    manifests = [
        KubeManifest.from_dict(parsed_yaml)
        for file in digest_contents
        for parsed_yaml in yaml.safe_load_all(file.content)
    ]

    logger.debug(
        f"Found {pluralize(len(manifests), 'manifest')} in {request.description_of_origin}"
    )
    return KubeManifests(manifests)


def rules():
    return collect_rules()
