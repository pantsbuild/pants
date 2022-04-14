# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum, unique
from typing import Any, cast

import yaml

from pants.engine.collection import Collection
from pants.engine.fs import Digest, DigestContents
from pants.engine.rules import Get, collect_rules, rule
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


@unique
class ResourceKind(Enum):
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
class ContainerRef:
    registry: str | None
    repository: str
    tag: str = _DEFAULT_CONTAINER_TAG

    @classmethod
    def parse(cls, image_ref: str) -> ContainerRef:
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
class ResourceManifest:
    api_version: str
    kind: ResourceKind | CustomResourceKind
    container_images: tuple[ContainerRef, ...]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ResourceManifest:
        std_kind: ResourceKind | None = None
        try:
            std_kind = ResourceKind(d["kind"])
        except ValueError:
            custom_kind = CustomResourceKind(d["kind"])

        container_images: list[ContainerRef] = []
        if std_kind:
            container_images = cls._extract_container_images(std_kind, d["spec"])

        return cls(
            api_version=d["apiVersion"],
            kind=std_kind or custom_kind,
            container_images=tuple(container_images),
        )

    @classmethod
    def _extract_container_images(
        cls, kind: ResourceKind, spec: dict[str, Any]
    ) -> list[ContainerRef]:
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
        if kind == ResourceKind.CRON_JOB:
            containers = get_containers(["jobTemplate", "spec", "template", "spec"])
        elif kind == ResourceKind.DAEMON_SET:
            containers = get_containers(["template", "spec"])
        elif kind == ResourceKind.DEPLOYMENT:
            containers = get_containers(["template", "spec"])
        elif kind == ResourceKind.JOB:
            containers = get_containers(["template", "spec"])
        elif kind == ResourceKind.POD:
            containers = get_containers([])
        elif kind == ResourceKind.REPLICA_SET:
            containers = get_containers(["template", "spec"])
        elif kind == ResourceKind.STATEFUL_SET:
            containers = get_containers(["template", "spec"])

        return [ContainerRef.parse(cast(str, container["image"])) for container in containers]


class ResourceManifests(Collection[ResourceManifest]):
    pass


@dataclass(frozen=True)
class ParseKubernetesManifests:
    digest: Digest
    description_of_origin: str


@rule
async def parse_kubernetes_manifests(request: ParseKubernetesManifests) -> ResourceManifests:
    digest_contents = await Get(DigestContents, Digest, request.digest)
    manifests = [
        ResourceManifest.from_dict(parsed_yaml)
        for file in digest_contents
        for parsed_yaml in yaml.safe_load_all(file.content)
    ]

    logger.debug(
        f"Found {pluralize(len(manifests), 'manifest')} in {request.description_of_origin}"
    )
    return ResourceManifests(manifests)


def rules():
    return collect_rules()
