---
title: "Deployments"
slug: "helm-deployments"
hidden: false
createdAt: "2022-07-19T13:16:00.000Z"
updatedAt: "2022-07-19T13:16:00.000Z"
---
> 🚧 Helm deployment support is in alpha stage
> 
> Pants has experimental support managing deployments via the `experimental-deploy` goal. Helm deployments provides with a basic implementation of this goal.
> 
> Please share feedback for what you need to use Pants with your Helm deployments by either [opening a GitHub issue](https://github.com/pantsbuild/pants/issues/new/choose) or [joining our Slack](doc:getting-help)!

Motivation
----------

Helm's ultimate purpose is to simplify the deployment of Kubernetes resources and help in making these reproducible. However is quite common to deploy the same software application into different kind of environments using slightly different configuration overrides.

This hinders reproducibility since operators end up having a set of configuration files and additional shell scripts that ensure that the Helm command line usued to deploy a piece of software into a given environment is always the same.

Pants solves this problem by providing with the ability to manage the configuration files and the different parameters of a deployment as single unit such that a simple command line as `./pants experimental-deploy ::` will always have the same effect on each of the deployments previously defined.

Defining Helm deployments
-------------------------

Helm deployments are defined using the `helm_deployment` target which has a series of fields that can be used to guarantee the reproducibility of the given deployment. `helm_deployment` targets need to be added by hand as there is no deterministic way of instrospecting your repository to find sources that are specific to Helm:

```text src/chart/BUILD
helm_chart()
```
```yaml src/chart/Chart.yaml
apiVersion: v2
description: Example Helm chart
name: example
version: 0.1.0
```
```text src/deployment/BUILD
helm_deployment(name="dev", sources=["common.yaml", "dev-override.yaml"], dependencies=["//src/chart"])

helm_deployment(name="stage", sources=["common.yaml", "stage-override.yaml"], dependencies=["//src/chart"])

helm_deployment(name="prod", sources=["common.yaml", "prod-override.yaml"], dependencies=["//src/chart"])
```
```yaml src/deployment/common.yaml
# Default values common to all deployments
env:
  SERVICE_NAME: my-service
```
```yaml src/deployment/dev-override.yaml
# Specific values to the DEV environment
env:
  ENV_ID: dev
```
```yaml src/deployment/stage-override.yaml
# Specific values to the STAGE environment
env:
  ENV_ID: stage
```
```yaml src/deployment/prod-override.yaml
# Specific values to the PRODUCTION environment
env:
  ENV_ID: prod
```

There are quite a few things to notice in the previous example:

* The `helm_deployment` target requires you to explicitly define as a dependency what is the chart to be used.
* We have three different deployments that using configuration files with the specified chart.
* One of those configuration files (`common.yaml`) is provides with default values that are common to all deployments.
* Each deployment uses an additional `xxx-override.yaml` file with values that are specific to the given deployment.

> 📘 Source roots
> 
> Don't forget to configure your source roots such that each of the shown files in the previous example sit at their respective source root level.

The `helm_deployment` target has many additional fields that cover from configuring the target namespace to even provide with inline overriding values. Please run `./pants help helm_deployment` to see all the posibilities.

Dependencies with `docker_image` targets
----------------------------------------

A Helm deployment will in most cases deploy one or more Docker images into Kubernetes. Furthermore, it's quite likely there is going to be at list some first party Docker images among those. Pants is capable of analysing the Helm chart being used in a deployment and detect those first-party Docker images if the chart being used, uses Pants' target addresses to those Docker images.

To illustrate this, let's imagine the following scenario: Let's say we have a first-party Docker image that we want to deploy into Kubernetes as a `Pod` resource kind. For achieving this we define the following workspace:

```text src/docker/BUILD
docker_image()
```
```text src/docker/Dockerfile
FROM busybox:1.28
```
```text src/chart/BUILD
helm_chart()
```
```yaml src/chart/Chart.yaml
apiVersion: v2
description: Example Helm chart
name: example
version: 0.1.0
```
```yaml src/chart/values.yaml
# Undefined image entry
image:
```
```yaml src/chart/templates/pod.yaml
---
apiVersion: v1
kind: Pod
metadata:
  name: my_pod
  labels:
    chart: "{{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}"
spec:
  containers:
    - name: my_app
      # Uses the `image` value entry from the deployment inputs
      image: {{ .Values.image }}
```
```text src/deployment/BUILD
# Uses the target address for the first-party docker image as the `image` entry for the chart.
helm_deployment(dependencies=["src/chart"], values={"image": "src/docker"})
```

With this setup we should be able to run `./pants dependencies src/deployment` and Pants should give the following output:

```text
src/chart
src/docker
```

This should work any kind of Kubernetes resource that will result in Docker image being deployed into Kubernetes, like `Deployment`, `StatefulSet`, `ReplicaSet`, `CronJob`, etc. Please get in touch with us in case you find Pants was not capable to infer dependencies in any of your `helm_deployment` targets by either [opening a GitHub issue](https://github.com/pantsbuild/pants/issues/new/choose) or [joining our Slack](doc:getting-help).

> 📘 Why using Pants' target addresses in the charts?
> 
> You can still use typical Docker registry addresses in your Helm charts and deployments if you want to use off-the-shelf images published with other means. Usage of Pants' target addresses is intended for your own first-party images because the image reference of those is not known at the time we create the sources (they are computed later).

Deploying
---------

Continuing with the example in the previous section, we can deploy it into Kubernetes using the command `./pants experimental-deploy src/deployment`. This will go trigger the following steps:

1. Analyse the dependencies of the given deployment.
2. Build and publish any first-party Docker image and Helm charts that are part of those dependencies.
3. Post-process the Kubernetes manifests generated by Helm by replacing all references to first-party Docker images by their real final registry destination.
4. Initiate the deployment of the final Kubernetes resources resulting from the post-processing.

The `experimental-deploy` goal also supports default Helm pass-through arguments that allow to change the deployment behaviour to be either atomic or a dry-run or even what is the Kubernetes config file and target context to be used in the deployment.

Please note that the list of valid pass-through arguments has been limited to those that not alter the reproducibility of the deployment (i.e. `--create-namespace` is not a valid pass-through argument). Those arguments will have equivalente fields in the `helm_deployment` target.