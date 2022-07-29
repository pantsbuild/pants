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
helm_deployment(name="dev", sources=["common-values.yaml", "dev-override.yaml"], dependencies=["//src/chart"])

helm_deployment(name="stage", sources=["common-values.yaml", "stage-override.yaml"], dependencies=["//src/chart"])

helm_deployment(name="prod", sources=["common-values.yaml", "prod-override.yaml"], dependencies=["//src/chart"])
```
```yaml src/deployment/common-values.yaml
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

* The `helm_deployment` target requires you to explicitly define as a dependency which chart to use.
* We have three different deployments that using configuration files with the specified chart.
* One of those value files (`common-values.yaml`) provides with default values that are common to all deployments.
* Each deployment uses an additional `xxx-override.yaml` file with values that are specific to the given deployment.

> 📘 Source roots
> 
> Don't forget to configure your source roots such that each of the shown files in the previous example sit at their respective source root level.

The `helm_deployment` target has many additional fields including the target kubernetes namespace, adding inline override values (similar to using helm's `--set` arg) and many others. Please run `./pants help helm_deployment` to see all the posibilities.

Dependencies with `docker_image` targets
----------------------------------------

A Helm deployment will in most cases deploy one or more Docker images into Kubernetes. Furthermore, it's quite likely there is going to be at least a few first party Docker images among those. Pants is capable of analysing the Helm chart being used in a deployment to detect those required first-party Docker images using Pants' target addresses to those Docker images.

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
# Default image in case this chart is used by other tools after being published
image: example.com/registry/my-app:latest
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
# Overrides the `image` value for the chart using the target address for the first-party docker image.
helm_deployment(dependencies=["src/chart"], values={"image": "src/docker"})
```

> 📘 Docker image references VS Pants' target addresses
> 
> You should use typical Docker registry addresses in your Helm charts. Because Helm charts are distributable artifacts and may be used with tools other than Pants, you should create your charts such that when that chart is being used, all Docker image addresses are valid references to images in accessible Docker registries. As shown in the example, we recommend that you make the image address value configurable, especially for charts that deploy first-party Docker images.
> Your chart resources can still use off-the-shelf images published with other means, and in those cases you will also be referencing the Docker image address. Usage of Pants' target addresses is intended for your own first-party images because the image reference of those is not known at the time we create the sources (they are computed later).

With this setup we should be able to run `./pants dependencies src/deployment` and Pants should give the following output:

```text
src/chart
src/docker
```

This should work with any kind of Kubernetes resource that leads to Docker image being deployed into Kubernetes, such as `Deployment`, `StatefulSet`, `ReplicaSet`, `CronJob`, etc. Please get in touch with us in case you find Pants was not capable to infer dependencies in any of your `helm_deployment` targets by either [opening a GitHub issue](https://github.com/pantsbuild/pants/issues/new/choose) or [joining our Slack](doc:getting-help).

> 📘 How the Docker image reference is calculated during deployment?
> 
> Pants' will rely on the behaviour of the `docker_image` target when it comes down to generate the final image reference. Since a given image may have more than one valid image reference, **Pants will try to use the first one that is not tagged as `latest`**, falling back to `latest` if none could be found.
> It's good practice to publish your Docker images using tags other than `latest` and Pants preferred behaviour is to choose those as this guarantees that the _version_ of the Docker image being deployed is the expected one.

Value override files
--------------------

As seen in the initial examples of the usage of the `helm_deployment` target, it can be seen that some of the source value files used the word `override` in the file name.

When using deployments that may have more than one YAML file as the source of configuration values, it is recommended use the `override` word in those filenames that are meant to override values coming from other more common or general sources.

Besides, you may be interested in organizing your deployment source files using a nested folder structure as the following:

```
src/deployment/config_maps.yaml
src/deployment/services.yaml
src/deployment/dev/services.yaml
src/deployment/uat/services.yaml
```

```text src/deployment/BUILD
helm_deployment(name="dev", dependencies=["//src/chart"], sources=["*.yaml", "dev/*.yaml"])

helm_deployment(name="uat", dependencies=["//src/chart"], sources=["*.yaml", "uat/*.yaml"])
```

In this case, files that are in nested folders will also act as value override files.

We believe that this approach gives enough flexibility to organise your deployment sources as you better prefer while providing an intuitive way to Pants' users to ensure that the list of value file sources is in the right order every single time.

In addition to value files, you can also use inline values in your `helm_deployment` targets by means of the `values` field. All inlines values that are set this way will override any entry that may come from value files, whether the source file was an override file or not. The relationship between the three scopes can be imagined as follows:

```
Value files < Value override files < Inline values
```

Deploying
---------

Continuing with the example in the previous section, we can deploy it into Kubernetes using the command `./pants experimental-deploy src/deployment`. This will trigger the following steps:

1. Analyse the dependencies of the given deployment.
2. Build and publish any first-party Docker image and Helm charts that are part of those dependencies.
3. Post-process the Kubernetes manifests generated by Helm by replacing all references to first-party Docker images by their real final registry destination.
4. Initiate the deployment of the final Kubernetes resources resulting from the post-processing.

The `experimental-deploy` goal also supports default Helm pass-through arguments that allow to change the deployment behaviour to be either atomic or a dry-run or even what is the Kubernetes config file and target context to be used in the deployment.

Please note that the list of valid pass-through arguments has been limited to those that do not alter the reproducibility of the deployment (i.e. `--create-namespace` is not a valid pass-through argument). Those arguments will have equivalent fields in the `helm_deployment` target.

For example, to make an atomic deployment into a non-default Kubernetes context you can use a command like the following one:

```
./pants experimental-deploy src/deployments:prod -- --kube-context my-custom-kube-context --atomic
```

> 📘 How does Pants authenticate with the Kubernetes cluster?
>
> Short answer is: it doesn't. 
> Pants will invoke Helm under the hood with the appropriate arguments to only perform the deployment. Any authentication steps that may be needed to perform the given deployment have to be done before invoking the `experimental-deploy` goal. If you are planning to run the deployment procedure from your CI/CD pipelines, ensure that all necessary preliminary steps are done before the one that triggers the deployment.