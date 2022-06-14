---
title: "Helm Overview"
slug: "helm-overview"
hidden: false
createdAt: "2022-05-13T16:06:59.247Z"
updatedAt: "2022-05-17T15:00:11.338Z"
---
> 🚧 Helm support is in alpha stage
> 
> Pants has good support for the most common operations for managing Helm charts sources. However there may be use cases not covered yet.
> 
> Please share feedback for what you need to use Pants with your Helm charts by either [opening a GitHub issue](https://github.com/pantsbuild/pants/issues/new/choose) or [joining our Slack](doc:getting-help)!

Initial setup
=============

First, activate the relevant backend in `pants.toml`:

```toml pants.toml
[GLOBAL]
backend_packages = [
  ...
  "pants.backend.experimental.helm",
  ...
]
```

In the case in which you may have more than one chart in the same repository, it is important that you configure your Pants' source roots in a way that Pants recognises each of your chart folders as a source root. In the following example `foo` and `bar` are Helm charts, so we give Pants a source root pattern to consider `src/helm/foo` and `src/helm/bar` as source roots.

```yaml src/helm/foo/Chart.yaml
apiVersion: v2
description: Foo Helm chart
name: foo
version: 0.1.0
```
```yaml src/helm/bar/Chart.yaml
apiVersion: v2
description: Bar Helm chart
name: bar
version: 0.1.0
```
```toml pants.toml
[source]
root_patterns = [
  ...
  "src/helm/*",
  ...
]
```

Adding `helm_chart` targets
---------------------------

Helm charts are identified by the presence of a `Chart.yaml` or `Chart.yml` file, which contains relevant metadata about the chart like its name, version, dependencies, etc. To get started quickly you can create a simple `Chart.yaml` file in your sources folder:

```text Chart.yaml
apiVersion: v2
description: Example Helm chart
name: example
version: 0.1.0
```

> 📘 Using `helm create`
> 
> You can use the `helm create` command to create an initial skeleton for your chart but be sure you have properly configured your source root patterns (as shown in the previous section) since the `helm create` command will create a folder name with the name of your chart and place the sources inside.

Then run [`./pants tailor`](doc:create-initial-build-files) to generate `BUILD` files. This will scan your source repository in search of `Chart.yaml` or `Chart.yml` files and create a `helm_chart` target for each of them.

```
❯ ./pants tailor
Created src/helm/example/BUILD:
  - Add helm_chart target example
```

Basic operations
----------------

The given setup is enough to now do some common operations on our Helm chart source code.

### Linting

The Helm backend has an implementation of the Pants' `lint` goal which hooks it with the `helm lint` command:

```
./pants lint ::
==> Linting example
[INFO] Chart.yaml: icon is recommended

1 chart(s) linted, 0 chart(s) failed


✓ helm succeeded.
```

The linting command is non-strict by default. If you want to enforce strict linting it can be either done globally in the `pants.toml` file, or in a per-chart target basis, using one of the two following ways:

```toml pants.toml
[helm]
# Enables strict linting globally
lint_strict = true
```
```python BUILD
helm_chart(lint_strict=True)
```

Likewise, in a similar way you could enable strict linting globally and then choose to disable it in a per-target basis. Run `./pants help helm` or `./pants help helm_chart` for more information.

### Package

Packing helm charts is supported out of the box via the Pants' `package` goal. The final package will be saved as a `.tgz` file under the `dist` folder at your source root.

```
./pants package ::
10:23:15.24 [INFO] Completed: Packaging Helm chart: testprojects/src/helm/example
10:23:15.24 [INFO] Wrote dist/testprojects.src.helm.example/example/example-0.2.0.tgz
Built Helm chart artifact: testprojects.src.helm.example/example/example-0.2.0.tgz
```

The final output folder can customised using the `output_path` field in the `helm_chart` target. Run `./pants help helm_chart` for more information.

Helm Unit tests
===============

The Helm backend supports running Helm unit tests via the [Helm `unittest` plugin](https://github.com/quintush/helm-unittest). To run unit tests follow the instructions on how to use that plugin and then create a `BUILD` file in the same folder where your tests live with the following target:

```python src/helm/example/tests/BUILD
helm_unittest_tests()
```
```yaml src/helm/example/templates/env-configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: example-configmap
data:
{{- range $envKey, $envVal := .Values.env }}
  {{ $envKey | upper }}: {{ $envVal | quote }}
{{- end }}
```
```yaml src/helm/example/tests/env-configmap_test.yaml
suite: test env-configmap
templates:
  - env-configmap.yaml
tests:
  - it: should contain the env map variables
    set:
      env:
        VAR1_NAME: var1Value
        var2_name: var2Value
    asserts:
      - equal:
          path: data.VAR1_NAME
          value: "var1Value"
      - equal:
          path: data.VAR2_NAME
          value: "var2Value"
```

With the test files in places, you can now run `./pants test ::` and Pants will execute each of your tests individually:

```
./pants test ::
10:50:12.45 [INFO] Completed: Running Helm unittest on: testprojects/src/helm/example/tests/env-configmap_test.yaml
10:50:12.46 [INFO] Completed: Run Helm Unittest - testprojects/src/helm/example/tests/env-configmap_test.yaml succeeded.

✓ testprojects/src/helm/example/tests/env-configmap_test.yaml succeeded in 0.75s.
```

Publishing Helm charts
======================

Pants only supports publishing Helm charts to OCI registries, a feature that was made generally available in Helm 3.8.

The publishing is done with Pants' `publish` goal but first you will need to tell Pants what are the possible destination registries where to upload your charts.

Configuring OCI registries
--------------------------

In a similar way as the `docker_image` target, a `helm_chart` target takes an optional `registries` field whose value is a list of registry endpoints (prefixed by the `oci://` protocol):

```python src/helm/example/BUILD
helm_chart(
  name="example",
  registries=[
    "oci://reg.company.internal"
  ]
)
```

The chart published from that given target will be uploaded to the OCI registry specified.

If you have several charts that have to be published into the same registries, you can add them to your `pants.toml` file and then reference them by using their alias prefixed by a `@` symbol.

You can also designate one or more registries as default and then charts that have no explicit `registries` field will use those default registries.

```toml pants.toml
[helm.registries.company-registry1]
address = "oci://reg1.company.internal"
default = true

[helm.registries.company-registry2]
address = "oci://reg2.company.internal"
```
```python src/example/BUILD
helm_chart(name="demo")

# This is equivalent to the previous target, 
# since company-registry1 is the default registry:
helm_chart(
    name="demo",
    registries=["@company-registry1"],
)

# You can mix named and direct registry references.
helm_chart(
    name="demo2",
    registries=[
        "@company-registry2",
        "oci://ext-registry.company-b.net:8443",
    ]
)
```

Setting a repository name
-------------------------

When publishing charts into an OCI registry, you most likely will be interested on separating them from other kind of OCI assets (i.e. container images). For doing so you can set a `repository` field in the `helm_chart` target so the chart artifact will be uploaded to the given path:

```python src/helm/example/BUILD
helm_chart(
  name="example",
  repository="charts"
)
```

With the previous setting, your chart would be published to your default registry under the `charts` folder like in `oci://myregistry.internal/charts/example-0.1.0.tgz`.

You can also set a default global repository in `pants.toml` as in the following example:

```toml pants.toml
[helm]
default_registry_repository = "charts"
```

Managing Chart Dependencies
===========================

Helm charts can depend on other charts, whether first-party charts defined in the same repo, or third-party charts published in a registry. Pants uses this dependency information to know when work needs to be re-run. 

> 📘 Chart.yaml version
> 
> To benefit from Pants dependency management and inference in your Helm charts, you will need to use `apiVersion: v2` in your `Chart.yaml` file.

`Chart.yaml` dependencies
-------------------------

Pants will automatically infer dependencies from the `Chart.yaml` file. 

For example, given two charts `foo` and `bar` and a dependency between them:

```yaml src/helm/foo/Chart.yaml
apiVersion: v2
description: Foo Helm chart
name: foo
version: 0.1.0
```
```python src/helm/foo/BUILD
helm_chart()
```
```yaml src/helm/bar/Chart.yaml
apiVersion: v2
description: Bar Helm chart
name: bar
version: 0.1.0
dependencies:
- name: foo
```
```python src/helm/bar/BUILD
helm_chart()
```

Then, running `./pants dependencies`on `bar` will list  `foo` as a dependency:

```
./pants dependencies src/helm/bar
src/helm/foo
```

Explicitly provided dependencies in `BUILD` files
-------------------------------------------------

If you prefer, you can let your BUILD files be the "source of truth" for dependencies, instead of specifying them in `Chart.yaml`:

```yaml src/helm/foo/Chart.yaml
apiVersion: v2
description: Foo Helm chart
name: foo
version: 0.1.0
```
```python src/helm/foo/BUILD
helm_chart()
```
```yaml src/helm/bar/Chart.yaml
apiVersion: v2
description: Bar Helm chart
name: bar
version: 0.1.0
```
```python src/helm/bar/BUILD
helm_chart(dependencies=["//src/helm/foo"])
```

In this case, the `./pants dependencies` command will show the same result and, in addition, Pants will modify its copy of `bar`'s `Chart.yaml` before using it, so that it includes `foo` in its dependency list. Note that Pants will not modify the original copy in your source tree, only the copy it uses in the sandboxed execution environment.

Third party chart artifacts
---------------------------

Third party charts are provided to Pants using the `helm_artifact` target:

```yaml 3rdparty/helm/BUILD
helm_artifact(
  artifact="chart_name",
  version="0.0.1",
  registry="...",     # Optional
  repository="...",   # Optional for OCI registries
)
```

Third party artifacts are resolved using `helm pull`. Other charts can reference them in the same way as first-party charts (either in the `Chart.yaml` or in the `BUILD` file).

When adding third party artifacts, the `artifact` and `version` fields are mandatory, in addition to one _origin_ from which to download the actual archive. There are two different origins supported: _classic Helm repositories_ and _OCI registries_.

For **classic repositories**, provide with the full URL to the location of the chart archive, excluding the archive file itself:

```python 3rdparty/helm/jetstack/BUILD
helm_artifact(
  artifact="cert-manager",
  version="v0.7.0",
  repository="https://charts.jetstack.io",
)
```

For **OCI registries**, you must provide with the URL to the registry in the `registry` field and an optional `repository` field with the path inside that registry.

```python 3rdparty/helm/example/BUILD
helm_artifact(
  artifact="foo",
  version="1.0.0",
  registry="oci://registry.example.com",
  repository="charts",
)
```