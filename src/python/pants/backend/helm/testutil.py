# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent  # noqa: PNT20

from pants.backend.helm.util_rules.chart_metadata import DEFAULT_API_VERSION, ChartType


def gen_chart_file(
    name: str,
    *,
    version: str,
    description: str | None = None,
    type: ChartType = ChartType.APPLICATION,
    api_version: str = DEFAULT_API_VERSION,
    icon: str | None = None,
) -> str:
    metadata_yaml = dedent(
        f"""\
    apiVersion: {api_version}
    name: {name}
    version: {version}
    type: {type.value}
    """
    )
    if description:
        metadata_yaml += f"description: {description}\n"
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

HELM_CHART_FILE_V1_FULL = dedent(
    """\
  name: foo
  version: 0.1.0
  kubeVersion: 1.17
  description: The foo chart
  keywords:
  - foo
  - chart
  home: https://example.com
  sources:
  - https://example.com/git
  dependencies:
  - name: bar
    version: 0.2.0
    repository: https://example.com/repo
    condition: bar.enabled
    tags:
    - foo
    - bar
    import-values:
    - data
    alias: bar-alias
  maintainers:
  - name: foo
    email: bar@example.com
    url: https://example.com/foo
  icon: https://example.com/icon.png
  appVersion: 0.1.0
  deprecated: true
  annotations:
    example: yes
    name: foo
  """
)

HELM_CHART_FILE_V2_FULL = dedent(
    """\
  apiVersion: v2
  name: quxx
  version: 0.1.0
  kubeVersion: 1.17
  description: The foo chart
  type: library
  keywords:
  - foo
  - chart
  home: https://example.com
  sources:
  - https://example.com/git
  dependencies:
  - name: bar
    version: 0.2.0
    repository: https://example.com/repo
    condition: bar.enabled
    tags:
    - foo
    - bar
    import-values:
    - data
    alias: bar-alias
  maintainers:
  - name: foo
    email: bar@example.com
    url: https://example.com/foo
  icon: https://example.com/icon.png
  appVersion: 0.1.0
  deprecated: true
  annotations:
    example: yes
    name: quxx
  """
)

K8S_SERVICE_TEMPLATE = dedent(
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

K8S_INGRESS_TEMPLATE_WITH_LINT_WARNINGS = dedent(
    """\
  apiVersion: extensions/v1beta1
  kind: Ingress
  metadata:
    name: {{ template "fullname" . }}
    labels:
      chart: "{{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}"
  spec:
    rules:
    - host: example.com
      http:
        paths:
        - path: /
          pathType: Prefix
          backend:
            service:
              name: {{ template "fullname" . }}
              port:
                name: http
  """
)

K8S_POD_TEMPLATE = dedent(
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

K8S_POD_FILE = dedent(
    """\
    apiVersion: v1
    kind: Pod
    metadata:
      name: foo
      labels:
        chart: foo-bar
    spec:
      containers:
        - name: myapp-container
          image: busybox:1.28
      initContainers:
        - name: init-service
          image: busybox:1.29
    """
)

K8S_CRD_FILE = dedent(
    """\
  apiVersion: apiextensions.k8s.io/v1
  kind: CustomResourceDefinition
  metadata:
  # name must match the spec fields below, and be in the form: <plural>.<group>
  name: myplatforms.contoso.com
  spec:
  # group name to use for REST API: /apis/<group>/<version>
  group: contoso.com
  names:
    # plural name to be used in the URL: /apis/<group>/<version>/<plural>
    plural: myplatforms
    # singular name to be used as an alias on the CLI and for display
    singular: myplatform
    # kind is normally the CamelCased singular type. Your resource manifests use this.
    kind: MyPlatform
    # shortNames allow shorter string to match your resource on the CLI
    shortNames:
    - myp
  # either Namespaced or Cluster
  scope: Namespaced
  versions:
    - name: v1alpha1
      # Each version can be enabled/disabled by Served flag.
      served: true
      # One and only one version must be marked as the storage version.
      storage: true
      schema:
        openAPIV3Schema:
          type: object
          properties:
            spec:
              type: object
              properties:
                appId:
                  type: string
                language:
                  type: string
                  enum:
                  - csharp
                  - python
                  - go
                os:
                  type: string
                  enum:
                  - windows
                  - linux
                instanceSize:
                  type: string
                  enum:
                    - small
                    - medium
                    - large
                environmentType:
                  type: string
                  enum:
                  - dev
                  - test
                  - prod
                replicas:
                  type: integer
                  minimum: 1
              required: ["appId", "language", "environmentType"]
          required: ["spec"]
  """
)

K8S_CUSTOM_RESOURCE_FILE = dedent(
    """\
    apiVersion: myplatforms.contoso.com/v1alpha1
    kind: MyPlatform
    metadata:
      name: cr_foo
    spec:
      appId: foo
      language: python
      environmentType: test
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

HELM_BATCH_HOOK_TEMPLATE = dedent(
    """\
  apiVersion: batch/v1
  kind: Job
  metadata:
    name: "{{ .Release.Name }}"
    labels:
      app.kubernetes.io/managed-by: {{ .Release.Service | quote }}
      app.kubernetes.io/instance: {{ .Release.Name | quote }}
      app.kubernetes.io/version: {{ .Chart.AppVersion }}
      helm.sh/chart: "{{ .Chart.Name }}-{{ .Chart.Version }}"
    annotations:
      # This is what defines this resource as a hook. Without this line, the
      # job is considered part of the release.
      "helm.sh/hook": post-install
      "helm.sh/hook-weight": "-5"
      "helm.sh/hook-delete-policy": hook-succeeded
  spec:
    template:
      metadata:
        name: "{{ .Release.Name }}"
        labels:
          app.kubernetes.io/managed-by: {{ .Release.Service | quote }}
          app.kubernetes.io/instance: {{ .Release.Name | quote }}
          helm.sh/chart: "{{ .Chart.Name }}-{{ .Chart.Version }}"
      spec:
        restartPolicy: Never
        containers:
        - name: post-install-job
          image: "alpine:3.3"
          command: ["/bin/sleep","{{ default "10" .Values.sleepyTime }}"]
  """
)
