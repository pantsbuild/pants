---
title: "Tagging Docker images"
slug: "tagging-docker-images"
excerpt: "How to set registry, repository and tag names on your images"
hidden: false
createdAt: "2021-10-04T15:50:36.840Z"
---
Configuring registries
----------------------

A `docker_image` target takes an optional `registries` field, whose value is a list of registry endpoints and aliases:

```python src/example/BUILD
docker_image(
    name="demo",
    registries=[
        "reg1.company.internal",
        "@company-registry2",
    ]
)
```

When publishing this image, it will be pushed to these registries by default.

In order to provide registry specific configuration, add them to the Pants configuration under
`[docker.registries.<alias>]` and refer to them by their alias from the `docker_image` targets,
using a `@` prefix.

Options for `registries` in `pants.toml`:

 * `address` - The registry endpoint.

 * `default` - Use this registry for all `docker_image` targets that does not provide a value for
   the `registries` field. Multiple registries may be used as default at the same time.

 * `extra_image_tags` - Registry specific version tags to apply to the image when using this
   registry.

 * `repository` - Format the repository part of the image name for this image. See [Setting a
   repository name](doc:tagging-docker-images#setting-a-repository-name) for details of this option.

 * `skip_push` - Do not push images to this registry during `pants publish`.

 * `use_local_alias` - Use the registry alias as a shorter name to use locally such as when running
   an image, useful if the address is unwieldy long. When building images using `pants package`,
   the image will be tagged with all image names for the target where as when simply running an
   image with `pants run` only the shorter image name will be tagged avoid cluttering the Docker
   images repository. The shorter image names are automatically skipped for any push operations.


Example:

```toml pants.toml
[docker.registries.company-registry1]
address = "reg1.company.internal"
default = true
extra_image_tags = ["dev"]

[docker.registries.company-registry2]
address = "reg2.company.internal"
skip_push = true

[docker.registries.company-registry3]
address = "reg3.company.internal"
repository = "{parent_directory}/{name}"
use_local_alias = true
```
```python src/example/BUILD
docker_image(name="demo")

# This is equivalent to the previous target, 
# since company-registry1 is the default registry:
docker_image(
    name="demo",
    registries=["@company-registry1"],
)

# You can mix named and direct registry references.
docker_image(
    name="demo2",
    registries=[
        "@company-registry2",
        "ext-registry.company-b.net:8443",
    ]
)
```

Setting a repository name
-------------------------

In Docker parlance, an image is identified by a _repository_ and one or more _tags_ within that repository. 

You set a repository name using the `repository` field on `docker_image`:

```python src/example/BUILD
docker_image(
    name="demo",
    repository="example/demo",
)
```
```shell
$ pants package src/example:demo
# Will build the image: example/demo:latest
```

To use a repository only for a specific registry, provide a `repository` value in the registry
configuration, and this can contain placeholders in curly braces that will be interpolated for each
image name.

```toml pants.toml
[docker.registries.demo]
address = "reg.company.internal"
repository = "example/{name}"
```

You can also specify a default repository name in config, and this name can contain placeholders in
curly braces that will be interpolated for each `docker_image`:

```toml pants.toml
[docker]
default_repository = "{directory}/{name}"
```
```python src/example/BUILD
docker_image(
    name="demo",
)
```

The default placeholders are:

- `{directory}`: The directory the docker_image's BUILD file is in.
- `{parent_directory}`: The parent directory of `{directory}`.
- `{name}`: The name of the docker_image target.
- `{build_args.ARG_NAME}`: Each defined Docker build arg is available for interpolation under the `build_args.` prefix.
- `{default_repository}`: The default repository from configuration.
- `{target_repository}`: The repository on the `docker_image` if provided, otherwise the default repository.

Since repository names often conform to patterns like these, this can save you on some boilerplate
by allowing you to omit the `repository` field on each `docker_image`. But you can always override
this field on specific `docker_image` targets, of course. In fact, you can use these placeholders in
the `repository` field as well, if you find that helpful.

See [String interpolation using placeholder values](doc:tagging-docker-images#string-interpolation-using-placeholder-values) for more information.


Tagging images
--------------

When Docker builds images, it can tag them with a set of tags. Pants will apply the tags listed in
the `image_tags` field of `docker_image`, and any additional tags if defined from the registry
configuration (see [Configuring registries](doc:tagging-docker-images#configuring-registries).

(Note that the field is named `image_tags` and not just `tags`, because Pants has [its own tags
concept](doc:reference-target#codetagscode), which is unrelated.)

```python src/example/BUILD
docker_image(
    name="demo",
    repository="example/demo",
    image_tags=["1.2", "example"]
)
```

When pants builds the `src/example:demo` target, a single image will be built, with two tags applied:

- `example/demo:1.2`
- `example/demo:example`

It's often useful to keep versions of derived images and their base images in sync. Pants helps you
out with this by interpolating tags referenced in `FROM` commands in your Dockerfile into the
`image_tags` in the corresponding `docker_image`:

```python src/example/BUILD
# These three are equivalent
docker_image(name="demo1", image_tags=["{tags.upstream}"])
docker_image(name="demo1", image_tags=["{tags.stage0}"])
# The first FROM may also be referred to as "baseimage"
docker_image(name="demo1", image_tags=["{tags.baseimage}"])

# Any stage my be used, and being a format string, you may add extra text as well.
docker_image(name="demo1", image_tags=["{tags.stage1}-custom-suffix"])
```
```dockerfile src/example/Dockerfile
FROM upstream:1.2 as upstream
# ...
FROM scratch
# ...
```

This way you can specify a version just once, on the base image, and the derived images will
automatically acquire the same version.

You may also use any Docker build arguments (when configured as described in [Docker build
arguments](doc:docker#build-arguments)) for interpolation into the `image_tags` in the corresponding
`docker_image`:

```python src/example/BUILD
docker_image(image_tags=["{build_args.ARG_NAME}"])
```

Using env vars to include dynamic data in tags
----------------------------------------------

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
$ GIT_COMMIT=$(git rev-parse HEAD) pants package src/example:demo
```

the value from the environment will be used. 

> 📘 Generating dynamic tags in a plugin
> 
> If you don't want to use the environment variable method described above, you'll need to write some custom plugin code. Don't hesitate to [reach out](doc:getting-help) for help with this.
> 
> We are looking into making some common dynamic data, such as the git sha, automatically available in the core Docker plugin in the future.


Providing additional image tags with a plugin
---------------------------------------------

For cases where more customization is required and using environment variables and interpolation is
not enough, the next option is to write a plugin to provide additional tags when building images.

Demonstrated with an example:

```python example/plugin.py
from pants.backend.docker.target_types import DockerImageTagsRequest, DockerImageTags
from pants.engine.unions import UnionRule
from pants.engine.rules import rule, collect_rules
from pants.engine.target import Target


class CustomDockerImageTagsRequest(DockerImageTagsRequest):
    @classmethod
    def is_applicable(cls, target: Target) -> bool:
        # Optional. Opt-out on a per target basis.
        if some-condition:
            return False
        else:
            return True


@rule
async def custom_image_tags(request: CustomDockerImageTagsRequest) -> DockerImageTags:
    custom_tags = ["some", "tags"]
    return DockerImageTags(custom_tags)


def rules():
    return (
        *collect_rules(),
        UnionRule(DockerImageTagsRequest, CustomDockerImageTagsRequest),
    )
```


All together: Registries, Repositories and Tags
-----------------------------------------------

To illustrate how all the above work together, this target:

```python src/example/BUILD
docker_image(
    name="demo",
    repository="example/demo",
    registries=["reg1", "reg2"],
    image_tags=["1.0", "latest"]
)
```

Will create a single image with these full names:

```
reg1/example/demo:1.0
reg1/example/demo:latest
reg2/example/demo:1.0
reg2/example/demo:latest
```

String interpolation using placeholder values
---------------------------------------------

As we've seen above, some fields of the `docker_image` support replacing placeholder values in curly braces with variable text, such as a build arg or base image tag for instance.

The interpolation context (the available placeholder values) depends on which field it is used in. These are the common values available for all fields:

- `{tags.<stage>}`: The tag of a base image (the `FROM` instruction) for a particular stage in the `Dockerfile`. The `<stage>` is either `stageN` where `N` is the numeric index of the stage, starting at `0`. The first stage, `stage0`, is also available under the pseudonym `baseimage`. If the stage is named (`FROM image AS my_stage`), then the tag value is also available under that name: `{tags.my_stage}`.
- `{build_args.ARG_NAME}`: Each defined Docker build arg is available for interpolation under the `build_args.` prefix.
- `{pants.hash}`: This is a unique hash value calculated from all input sources and the `Dockerfile`. It is effectively a hash of the Docker build context. See note below regarding its stability guarantee.

See [Setting a repository name](doc:tagging-docker-images#setting-a-repository-name) for placeholders specific to the `repository` field.

> 📘 The `{pants.hash}` stability guarantee
> 
> The calculated hash value _may_ change between stable versions of Pants for the otherwise same input sources.

Retrieving the tags of an packaged image
----------------------------------------

When a docker image is packaged, metadata about the resulting image is output to a JSON file artefact. This includes the image ID, as well as the full names that the image was tagged with. This file is written in the same manner as outputs of other packageable targets and available for later steps (for example, a test with `runtime_package_dependencies` including the docker image target) or in `dist/` after `pants package`. By default, this is available at `path.to.target/target_name.docker-info.json`.

The structure of this JSON file is:

``` javascript
{
    "version": 1, // always 1, until a breaking change is made to this schema
    "image_id": "sha256:..." // the local Image ID of the computed image
    "registries": [ // info about each registry used for this image
        {
            "alias": "name", // set if the registry is configured in pants.toml, or null if not
            "address": "reg.invalid", // the address of the registry itself
            "repository": "the/repo", // the repository used for the image within the registry
            "tags": [
                {
                    "template": "tag-{...}", // the tag before substituting any placeholders
                    "tag": "tag-some-value", // the fully-substituted tag, actually used to tag the image
                    "uses_local_alias": false, // if this tag used the local alias for the registry or not
                    "name": "reg.invalid/the/repo:tag-some-value", // the full name that the image was tagged with
                }
            ]
        }
    ]
}
```

This JSON file can be used to retrieve the exact name to place into cloud deploy templates or to use for running locally, especially when using tags with placeholders.
