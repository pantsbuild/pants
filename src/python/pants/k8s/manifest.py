# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum, unique
from typing import Any, Iterable

import yaml
from yamlpath import YAMLPath

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


@dataclass(frozen=True)
class CustomResourceKind:
    value: str


@dataclass(frozen=True)
class ImageRef:
    registry: str | None
    repository: str
    tag: str | None

    @classmethod
    def parse(cls, image_ref: str) -> ImageRef:
        registry = None
        tag = None

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
        result = ""
        if self.registry:
            result += f"{self.registry}/"
        result += self.repository
        if self.tag:
            result += f":{self.tag}"
        return result


@dataclass(frozen=True)
class KubeContainer:
    image: ImageRef

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> KubeContainer:
        return cls(image=ImageRef.parse(d["image"]))


@dataclass(frozen=True)
class KubePodSpec:
    containers: tuple[KubeContainer, ...]
    init_containers: tuple[KubeContainer, ...]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> KubePodSpec:
        containers = d.get("containers", [])
        init_containers = d.get("initContainers", [])
        return cls(
            containers=tuple(KubeContainer.from_dict(c) for c in containers),
            init_containers=tuple(KubeContainer.from_dict(c) for c in init_containers),
        )

    @staticmethod
    def from_manifest_dict(
        resource_kind: StandardKind, d: dict[str, Any]
    ) -> tuple[YAMLPath, KubePodSpec] | None:
        """Parses the Kubernetes pod specification from the top level definition of a Kubernetes
        resource.

        Returns a tuple with the template spec and the path inside the resource spec where it was
        found.
        """

        def safe_get(path: Iterable[str]) -> Any | None:
            lookup_from = d
            result = None
            for path_elem in path:
                result = lookup_from.get(path_elem)
                lookup_from = result or {}
                if not result:
                    break
            return result

        def get_spec(path: Iterable[str]) -> tuple[str, dict[str, Any] | None]:
            return ".".join(path), (safe_get(path) if path else d)

        path = ""
        spec = None
        if resource_kind == StandardKind.CRON_JOB:
            path, spec = get_spec(["jobTemplate", "spec", "template", "spec"])
        elif resource_kind == StandardKind.DAEMON_SET:
            path, spec = get_spec(["template", "spec"])
        elif resource_kind == StandardKind.DEPLOYMENT:
            path, spec = get_spec(["template", "spec"])
        elif resource_kind == StandardKind.JOB:
            path, spec = get_spec(["template", "spec"])
        elif resource_kind == StandardKind.POD:
            path, spec = get_spec([])
        elif resource_kind == StandardKind.REPLICA_SET:
            path, spec = get_spec(["template", "spec"])
        elif resource_kind == StandardKind.STATEFUL_SET:
            path, spec = get_spec(["template", "spec"])

        if not spec:
            return None
        return YAMLPath(path), KubePodSpec.from_dict(spec)

    @property
    def all_containers(self) -> tuple[KubeContainer, ...]:
        result = [*self.containers, *self.init_containers]
        return tuple(result)


@dataclass(frozen=True)
class KubeManifest:
    filename: str

    api_version: str
    kind: StandardKind | CustomResourceKind
    _pod_spec: tuple[YAMLPath, KubePodSpec] | None

    @classmethod
    def from_dict(cls, filename: str, d: dict[str, Any]) -> KubeManifest:
        std_kind: StandardKind | None = None
        try:
            std_kind = StandardKind(d["kind"])
        except ValueError:
            custom_kind = CustomResourceKind(d["kind"])

        spec = None
        if std_kind:
            spec = KubePodSpec.from_manifest_dict(std_kind, d["spec"])

        return cls(
            filename=filename,
            api_version=d["apiVersion"],
            kind=std_kind or custom_kind,
            _pod_spec=spec,
        )

    @property
    def container_images(self) -> tuple[ImageRef, ...]:
        if not self.pod_spec:
            return ()
        return tuple(cont.image for cont in self.pod_spec.all_containers)

    @property
    def pod_spec(self) -> KubePodSpec | None:
        return self._pod_spec[1] if self._pod_spec else None

    @property
    def pod_spec_path(self) -> YAMLPath | None:
        return self._pod_spec[0] if self._pod_spec else None


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
        KubeManifest.from_dict(file.path, parsed_yaml)
        for file in digest_contents
        for parsed_yaml in yaml.safe_load_all(file.content)
    ]

    logger.debug(
        f"Found {pluralize(len(manifests), 'manifest')} in {request.description_of_origin}"
    )
    return KubeManifests(manifests)


def rules():
    return collect_rules()
