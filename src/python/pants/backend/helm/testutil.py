# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

from pants.backend.helm.util_rules.chart import ChartType


def gen_chart_file(
    name: str,
    *,
    version: str,
    type: ChartType = ChartType.APPLICATION,
    api_version: str = "v2",
    icon: str | None = None,
) -> str:
    metadata_yaml = dedent(
        f"""\
    apiVersion: {api_version}
    name: {name}
    description: A Helm chart for Kubernetes
    version: {version}
    type: {type.value}
    """
    )
    if icon:
        metadata_yaml += f"icon: {icon}\n"
    return metadata_yaml


HELM_CHART_FILE = gen_chart_file("mychart", version="0.1.0")

HELM_CHART_WITH_DEPENDENCIES_FILE = dedent(
    """\
    apiVersion: v2
    name: mychart
    description: A Helm chart for Kubernetes
    version: 0.1.0
    icon: https://www.example.com/icon.png
    dependencies:
    - name: other_chart
      repository: "@myrepo"
      version: "~0.1.0"
      alias: dependency_alias
    """
)

K8S_SERVICE_FILE = dedent(
    """\
  apiVersion: v1
  kind: Service
  metadata:
    name: {{ template "fullname" . }}
    labels:
      chart: "{{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}"
  spec:
    type: {{ .Values.service.type }}
    ports:
        - port: {{ .Values.service.externalPort }}
          targetPort: {{ .Values.service.internalPort }}
          protocol: TCP
          name: {{ .Values.service.name }}
    selector:
        app: {{ template "fullname" . }}
  """
)

K8S_POD_FILE = dedent(
    """\
  apiVersion: v1
  kind: Pod
  metadata:
    name: {{ template "fullname" . }}
    labels:
      chart: "{{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}"
  spec:
    containers:
      - name: myapp-container
        image: busybox:1.28
    initContainers:
      - name: init-service
        image: busybox:1.29
  """
)

HELM_TEMPLATE_HELPERS_FILE = dedent(
    """\
  {{- define "fullname" -}}
  {{- if .Values.fullnameOverride }}
  {{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
  {{- else }}
  {{- $name := default .Chart.Name .Values.nameOverride }}
  {{- if contains $name .Release.Name }}
  {{- .Release.Name | trunc 63 | trimSuffix "-" }}
  {{- else }}
  {{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
  {{- end }}
  {{- end }}
  {{- end }}
  """
)

HELM_VALUES_FILE = dedent(
    """\
  service:
    name: test
    type: ClusterIP
    externalPort: 80
    internalPort: 1223
  """
)
