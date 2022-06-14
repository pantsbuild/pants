---
title: "Tagging Docker images"
slug: "tagging-docker-images"
excerpt: "How to set registry, repository and tag names on your images"
hidden: false
createdAt: "2021-10-04T15:50:36.840Z"
updatedAt: "2022-04-22T08:17:48.824Z"
---
[block:api-header]
{
  "title": "Configuring registries"
}
[/block]
A `docker_image` target takes an optional `registries` field, whose value is a list of registry endpoints:
[block:code]
{
  "codes": [
    {
      "code": "docker_image(\n    name=\"demo\",\n    registries=[\n        \"reg.company.internal\",\n    ]\n)",
      "language": "python",
      "name": "src/example/BUILD"
    }
  ]
}
[/block]
Images built from this target will be published to these registries.

If you push many images to the same registries, and you don't want to repeat the endpoint information, you can name the registries in your `pants.toml` config file, and then refer to them by name in the target, using a `@` prefix.

You can also designate one or more registries as the default for your repo, and images with no explicit `registries` field will use those default registries.
[block:code]
{
  "codes": [
    {
      "code": "[docker.registries.company-registry1]\naddress = \"reg1.company.internal\"\ndefault = true\n\n[docker.registries.company-registry2]\naddress = \"reg2.company.internal\"",
      "language": "toml",
      "name": "pants.toml"
    },
    {
      "code": "docker_image(name=\"demo\")\n\n# This is equivalent to the previous target, \n# since company-registry1 is the default registry:\ndocker_image(\n    name=\"demo\",\n    registries=[\"@company-registry1\"],\n)\n\n# You can mix named and direct registry references.\ndocker_image(\n    name=\"demo2\",\n    registries=[\n        \"@company-registry2\",\n        \"ext-registry.company-b.net:8443\",\n    ]\n)",
      "language": "python",
      "name": "src/example/BUILD"
    }
  ]
}
[/block]

[block:api-header]
{
  "title": "Setting a repository name"
}
[/block]
In Docker parlance, an image is identified by a *repository* and one or more *tags* within that repository. 

You set a repository name using the `repository` field on `docker_image`:
[block:code]
{
  "codes": [
    {
      "code": "docker_image(\n    name=\"demo\",\n    repository=\"example/demo\",\n)",
      "language": "python",
      "name": "src/example/BUILD"
    }
  ]
}
[/block]
```shell
$ ./pants package src/example:demo
# Will build the image: example/demo:latest
```

You can also specify a default repository name in config, and this name can contain placeholders in curly braces that will be interpolated for each `docker_image`:
[block:code]
{
  "codes": [
    {
      "code": "[docker]\ndefault_repository = \"{directory}/{name}\"",
      "language": "toml",
      "name": "pants.toml"
    },
    {
      "code": "docker_image(\n    name=\"demo\",\n)",
      "language": "python",
      "name": "src/example/BUILD"
    }
  ]
}
[/block]
The default placeholders are:
- `{directory}`: The directory the docker_image's BUILD file is in.
- `{parent_directory}`: The parent directory of `{directory}`.
- `{name}`: The name of the docker_image target.
- `{build_args.ARG_NAME}`: Each defined Docker build arg is available for interpolation under the `build_args.` prefix.

Since repository names often conform to patterns like these, this can save you on some boilerplate by allowing you to omit the `repository` field on each `docker_image`. But you can always override this field on specific `docker_image` targets, of course. In fact, you can use these placeholders in the `repository` field as well, if you find that helpful.

See [String interpolation using placeholder values](doc:tagging-docker-images#string-interpolation-using-placeholder-values) for more information.
[block:api-header]
{
  "title": "Tagging images"
}
[/block]
When Docker builds images, it can tag them with a set of tags. Pants will apply the tags listed in the `image_tags` field of `docker_image`. 

(Note that the field is named `image_tags` and not just `tags`, because Pants has [its own tags concept](doc:reference-target#codetagscode), which is unrelated.)
[block:code]
{
  "codes": [
    {
      "code": "docker_image(\n    name=\"demo\",\n    repository=\"example/demo\",\n    image_tags=[\"1.2\", \"example\"]\n)",
      "language": "python",
      "name": "src/example/BUILD"
    }
  ]
}
[/block]
When pants builds the `src/example:demo` target, a single image will be built, with two tags applied:
- `example/demo:1.2`
- `example/demo:example`

It's often useful to keep versions of derived images and their base images in sync. Pants helps you out with this by interpolating tags referenced in `FROM` commands in your Dockerfile into the `image_tags` in the corresponding `docker_image`:
[block:code]
{
  "codes": [
    {
      "code": "# These three are equivalent\ndocker_image(name=\"demo1\", image_tags=[\"{tags.upstream}\"])\ndocker_image(name=\"demo1\", image_tags=[\"{tags.stage0}\"])\n# The first FROM may also be referred to as \"baseimage\"\ndocker_image(name=\"demo1\", image_tags=[\"{tags.baseimage}\"])\n\n# Any stage my be used, and being a format string, you may add extra text as well.\ndocker_image(name=\"demo1\", image_tags=[\"{tags.stage1}-custom-suffix\"])\n",
      "language": "python",
      "name": "src/example/BUILD"
    },
    {
      "code": "FROM upstream:1.2 as upstream\n# ...\nFROM scratch\n# ...\n",
      "language": "dockerfile",
      "name": "src/example/Dockerfile"
    }
  ]
}
[/block]
This way you can specify a version just once, on the base image, and the derived images will automatically acquire the same version. 

You may also use any Docker build arguments (when configured as described in [Docker build arguments](doc:docker#build-arguments)) for interpolation into the `image_tags` in the corresponding `docker_image`:
[block:code]
{
  "codes": [
    {
      "code": "docker_image(image_tags=[\"{build_args.ARG_NAME}\"])",
      "language": "python",
      "name": "src/example/BUILD"
    }
  ]
}
[/block]

[block:api-header]
{
  "title": "Using env vars to include dynamic data in tags"
}
[/block]
You can interpolate dynamic data, such as the current Git commit sha, in an image tag, using environment variables and Docker build args.

For example, you can declare a custom build arg, either in `extra_build_args` for a specific `docker_image` target, or for all `docker_image` targets in `pants.toml`:

```python
# pants.toml
[docker]
build_args = ["GIT_COMMIT"]
```

and use this build arg in the image tag:

```python
# src/example/BUILD
docker_image(name="demo", image_tags=["1.2-{build_args.GIT_COMMIT}"])
```

Then, if you run Pants with the data set in an environment variable of the same name:

```
$ GIT_COMMIT=$(git rev-parse HEAD) ./pants package src/example:demo
```

the value from the environment will be used. 
[block:callout]
{
  "type": "info",
  "body": "If you don't want to use the environment variable method described above, you'll need to write some custom plugin code. Don't hesitate to [reach out](doc:getting-help) for help with this.\n\nWe are looking into making some common dynamic data, such as the git sha, automatically available in the core Docker plugin in the future.",
  "title": "Generating dynamic tags in a plugin"
}
[/block]

[block:api-header]
{
  "title": "All together: Registries, Repositories and Tags"
}
[/block]
To illustrate how all the above work together, this target:
[block:code]
{
  "codes": [
    {
      "code": "docker_image(\n    name=\"demo\",\n    repository=\"example/demo\",\n    registries=[\"reg1\", \"reg2\"],\n    image_tags=[\"1.0\", \"latest\"]\n)",
      "language": "python",
      "name": "src/example/BUILD"
    }
  ]
}
[/block]
Will create a single image with these full names:

```
reg1/example/demo:1.0
reg1/example/demo:latest
reg2/example/demo:1.0
reg2/example/demo:latest
```
[block:api-header]
{
  "title": "String interpolation using placeholder values"
}
[/block]
As we've seen above, some fields of the `docker_image` support replacing placeholder values in curly braces with variable text, such as a build arg or base image tag for instance.

The interpolation context (the available placeholder values) depends on which field it is used in. These are the common values available for all fields:
- `{tags.<stage>}`: The tag of a base image (the `FROM` instruction) for a particular stage in the `Dockerfile`. The `<stage>` is either `stageN` where `N` is the numeric index of the stage, starting at `0`. The first stage, `stage0`, is also available under the pseudonym `baseimage`. If the stage is named (`FROM image AS my_stage`), then the tag value is also available under that name: `{tags.my_stage}`.
- `{build_args.ARG_NAME}`: Each defined Docker build arg is available for interpolation under the `build_args.` prefix.
- `{pants.hash}`: This is a unique hash value calculated from all input sources and the `Dockerfile`. It is effectively a hash of the Docker build context. See note below regarding its stability guarantee.

See [Setting a repository name](doc:tagging-docker-images#setting-a-repository-name) for placeholders specific to the `repository` field.
[block:callout]
{
  "type": "info",
  "title": "The `{pants.hash}` stability guarantee",
  "body": "The calculated hash value _may_ change between stable versions of Pants for the otherwise same input sources."
}
[/block]