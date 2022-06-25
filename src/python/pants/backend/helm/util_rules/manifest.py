# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum, unique
from pathlib import PurePath
from typing import Any

import yaml

from pants.backend.helm.util_rules.yaml_utils import YamlElement, YamlPath
from pants.engine.collection import Collection
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import Digest, DigestContents, DigestSubset, PathGlobs
from pants.engine.rules import Get, collect_rules, rule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize, softwrap

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
class KubeContainer(YamlElement):
    image: ImageRef

    @classmethod
    def from_dict(cls, path: YamlPath, d: dict[str, Any]) -> KubeContainer:
        return cls(element_path=path, image=ImageRef.parse(d["image"]))


@dataclass(frozen=True)
class KubePodSpec(YamlElement):
    containers: tuple[KubeContainer, ...]
    init_containers: tuple[KubeContainer, ...]

    @classmethod
    def from_dict(cls, path: YamlPath, d: dict[str, Any]) -> KubePodSpec:
        containers = d.get("containers", [])
        init_containers = d.get("initContainers", [])
        return cls(
            element_path=path,
            containers=tuple(
                KubeContainer.from_dict(path / "containers" / str(idx), c)
                for idx, c in enumerate(containers)
            ),
            init_containers=tuple(
                KubeContainer.from_dict(path / "initContainers" / str(idx), c)
                for idx, c in enumerate(init_containers)
            ),
        )

    @staticmethod
    def from_manifest_dict(
        base_path: YamlPath, resource_kind: StandardKind, d: dict[str, Any]
    ) -> KubePodSpec | None:
        """Parses the Kubernetes pod specification from the top level definition of a Kubernetes
        resource.

        Returns a tuple with the template spec and the path inside the resource spec where it was
        found.
        """

        def safe_get(path: YamlPath) -> Any | None:
            lookup_from = d
            result = None
            for path_elem in path:
                result = lookup_from.get(path_elem)
                lookup_from = result or {}
                if not result:
                    break
            return result

        def get_spec(path: YamlPath) -> tuple[YamlPath, dict[str, Any] | None]:
            return path, (safe_get(path) if path else d)

        path = base_path
        spec = None
        if resource_kind == StandardKind.CRON_JOB:
            path, spec = get_spec(path / "jobTemplate/spec/template/spec")
        elif resource_kind == StandardKind.DAEMON_SET:
            path, spec = get_spec(path / "template/spec")
        elif resource_kind == StandardKind.DEPLOYMENT:
            path, spec = get_spec(path / "template/spec")
        elif resource_kind == StandardKind.JOB:
            path, spec = get_spec(path / "template/spec")
        elif resource_kind == StandardKind.POD:
            path, spec = get_spec(path)
        elif resource_kind == StandardKind.REPLICA_SET:
            path, spec = get_spec(path / "template/spec")
        elif resource_kind == StandardKind.STATEFUL_SET:
            path, spec = get_spec(path / "template/spec")

        if not spec:
            return None
        return KubePodSpec.from_dict(path, spec)

    @property
    def all_containers(self) -> tuple[KubeContainer, ...]:
        result = [*self.containers, *self.init_containers]
        return tuple(result)


@dataclass(frozen=True)
class KubeManifest:
    filename: PurePath
    document_index: int

    api_version: str
    kind: StandardKind | CustomResourceKind
    pod_spec: KubePodSpec | None

    @classmethod
    def from_dict(
        cls, filename: PurePath, d: dict[str, Any], *, document_index: int = 0
    ) -> KubeManifest:
        std_kind: StandardKind | None = None
        try:
            std_kind = StandardKind(d["kind"])
        except ValueError:
            custom_kind = CustomResourceKind(d["kind"])

        spec = None
        if std_kind:
            base_path = YamlPath.parse("spec")
            spec = KubePodSpec.from_manifest_dict(base_path, std_kind, d)

        return cls(
            filename=filename,
            api_version=d["apiVersion"],
            kind=std_kind or custom_kind,
            pod_spec=spec,
            document_index=document_index,
        )

    @property
    def all_containers(self) -> tuple[KubeContainer, ...]:
        if not self.pod_spec:
            return ()
        return self.pod_spec.all_containers


class KubeManifests(Collection[KubeManifest]):
    pass


@dataclass(frozen=True)
class ParseKubeManifests(EngineAwareParameter):
    digest: Digest
    description_of_origin: str

    def debug_hint(self) -> str | None:
        return self.description_of_origin


@rule(desc="Parsing Kubernetes manifests", level=LogLevel.DEBUG)
async def parse_kubernetes_manifests(request: ParseKubeManifests) -> KubeManifests:
    yaml_subset = await Get(
        Digest, DigestSubset(request.digest, PathGlobs(["**/*.yaml", "**/*.yml"]))
    )
    digest_contents = await Get(DigestContents, Digest, yaml_subset)

    manifests = [
        KubeManifest.from_dict(PurePath(file.path), parsed_yaml, document_index=idx)
        for file in digest_contents
        for idx, parsed_yaml in enumerate(yaml.safe_load_all(file.content))
    ]

    logger.debug(
        softwrap(
            f"""
            Found {pluralize(len(manifests), 'manifest')} in
            {pluralize(len(digest_contents), 'file')} at {request.description_of_origin}.
            """
        )
    )
    return KubeManifests(manifests)


def rules():
    return collect_rules()
