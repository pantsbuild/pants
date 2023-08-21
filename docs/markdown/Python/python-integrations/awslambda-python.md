---
title: "AWS Lambda"
slug: "awslambda-python"
excerpt: "Create a Lambda with Python code."
hidden: false
createdAt: "2020-05-05T16:51:03.851Z"
---
Pants can create a Lambda-compatible zip file from your Python code, allowing you to develop your Lambdas in your repository instead of using the online Cloud9 editor.

> 📘 FYI: how Pants does this
>
> Under-the-hood, Pants uses the [PEX](https://github.com/pantsbuild/pex) project, to select the appropriate third-party requirements and first-party sources and lay them out in a zip file, in the format recommended by AWS.

Step 1: Activate the Python AWS Lambda backend
----------------------------------------------

Add this to your `pants.toml`:

```toml pants.toml
[GLOBAL]
backend_packages.add = [
  "pants.backend.awslambda.python",
  "pants.backend.python",
]
```

This adds the new `python_awslambda` target, which you can confirm by running `pants help python_awslambda`

> 🚧 Set `layout = "zip"` for Pants 2.17
>
> Pants 2.17 is transitioning to a new, better layout, but defaults to the old Lambdex layout for backwards compatibility. To silence the warnings and be ready for Pants 2.18, add the following to the end of your `pants.toml`:
>
> ```toml pants.toml
> [lambdex]
> layout = "zip"
> ```
>
> If you have existing `python_awslambda` targets, this will change the handler from `lambdex_handler.handler` to `lambda_function.handler` (see [below](#migrating-from-pants-216-and-earlier) for more details).

Step 2: Define a `python_awslambda` target
------------------------------------------

First, add your lambda function in a Python file like you would [normally do with AWS Lambda](https://docs.aws.amazon.com/lambda/latest/dg/python-handler.html). Specifically, create a function `def my_handler_name(event, context)` with the name you want.

Then, in your BUILD file, make sure that you have a `python_source` or `python_sources` target with the handler file included in the `sources` field. You can use [`pants tailor ::`](doc:initial-configuration#5-generate-build-files) to automate this.

Add a `python_awslambda` target and define the `runtime` and `handler` fields. The `runtime` should be one of the values from <https://docs.aws.amazon.com/lambda/latest/dg/lambda-python.html>. The `handler` has the form `handler_file.py:handler_func`, which Pants will convert into a well-formed entry point. Alternatively, you can set `handler` to the format `path.to.module:handler_func`.

For example:

```python project/BUILD
# The default `sources` field will include our handler file.
python_sources(name="lib")

python_awslambda(
    name="lambda",
    runtime="python3.8",
    # Pants will convert this to `project.lambda_example:example_handler`.
    handler="lambda_example.py:example_handler",
)
```
```python project/lambda_example.py
def example_handler(event, context):
    print("Hello AWS!")
```

Pants will use [dependency inference](doc:targets) based on the `handler` field, which you can confirm by running `pants dependencies path/to:lambda`. You can also manually add to the `dependencies` field.

You can optionally set the `output_path` field to change the generated zip file's path.

> 🚧 Use `resource` instead of `file`
>
> `file` / `files` targets will not be included in the built AWS Lambda because filesystem APIs like `open()` would not load them as expected. Instead, use the `resource` and `resources` target. See [Assets and archives](doc:assets) for further explanation.

Step 3: Run `package`
---------------------

Now run `pants package` on your `python_awslambda` target to create a zipped file.

For example:

```bash
$ pants package project/:lambda
Wrote dist/project/lambda.zip
  Handler: lambda_function.handler
```

> 🚧 Running from macOS and failing to build?
>
> AWS Lambdas must run on Linux, so Pants tells PEX and Pip to build for Linux when resolving your third party dependencies. This means that you can only use pre-built [wheels](https://packaging.python.org/glossary/#term-wheel) (bdists). If your project requires any source distributions ([sdists](https://packaging.python.org/glossary/#term-source-distribution-or-sdist)) that must be built locally, PEX and pip will fail to run.
>
> If this happens, you must either change your dependencies to only use dependencies with pre-built [wheels](https://pythonwheels.com) or find a Linux environment to run `pants package`.

Step 4: Upload to AWS
---------------------

You can use any of the various AWS methods to upload your zip file, such as the AWS console or the AWS CLI via `aws lambda create-function` and `aws lambda update-function-code`.

You can specify the AWS lambda handler as `lambda_function.handler`. This is a re-export of the function referred to by the `handler` field of the target.

Docker Integration
------------------

To [deploy a Python lambda function with container images](https://docs.aws.amazon.com/lambda/latest/dg/python-image.html), you can use Pants's [Docker](doc:docker) support.

For example:

```dockerfile project/Dockerfile
FROM public.ecr.aws/lambda/python:3.8

RUN yum install unzip -y
COPY project/lambda.zip .
RUN unzip lambda.zip -d "${LAMBDA_TASK_ROOT}"
CMD ["lambda_function.handler"]
```
```python project/BUILD
python_sources()

python_awslambda(
    name="lambda",
    runtime="python3.8",
    handler="main.py:lambda_handler"
)

docker_image(
    name="my_image",
    dependencies = [":lambda"],
)
```

Then, use `pants package project:my_image`, for example. Pants will first build your AWS Lambda, and then will build the Docker image and copy it into the AWS Lambda.

Advanced: Using PEX directly
----------------------------

In the rare case where you need access to PEX features, such as dynamic selection of dependencies, a PEX file created by `pex_binary` can be used as a Lambda package directly. A PEX file is a carefully constructed zip file, and can be understood natively by AWS. Note: using `pex_binary` results in larger packages and slower cold starts and is likely to be less convenient than using `python_awslambda`.

The handler of a `pex_binary` is not re-exported at the fixed `lambda_function.handler` path, and the Lambda handler must be configured as the `__pex__` pseudo-package followed by the handler's normal module path (for instance, if the handler is called `func` in `some/module/path.py` within [a source root](doc:source-roots), then use `__pex__.some.module.path.func`). The `__pex__` pseudo-package ensures dependencies are initialized before running any of your code.

For example:

```python project/BUILD
python_sources()

pex_binary(
    name="lambda",
    entry_point="lambda_example.py",
    # specify an appropriate platform(s) for the targeted Lambda runtime (complete_platforms works too)
    platforms=["linux_x86_64-cp39-cp39"],
)
```
```python project/lambda_example.py
def example_handler(event, context):
    print("Hello AWS!")
```

Then, use  `pants package project:lambda`, and upload the resulting `project/lambdex.pex` to AWS.  The handler will need to be configured in AWS as `__pex__.lambda_example.example_handler` (assuming `project` is a [source root](doc:source-roots)).

Migrating from Pants 2.16 and earlier
-------------------------------------

Pants has implemented a new way to package Lambdas in 2.17, resulting in smaller packages and faster cold starts. This involves some changes:

- In Pants 2.16 and earlier, Pants used the [Lambdex](https://github.com/pantsbuild/lambdex) project. First, Pants would convert your code into a [Pex file](doc:pex-files) and then use Lambdex to adapt this to be better understood by AWS by adding a shim handler at the path `lambdex_handler.handler`. This shim handler first triggers the Pex initialization to choose and unzip dependencies, during the "INIT" phase.
- In Pants 2.17, the use of Lambdex is deprecated, in favour of choosing the appropriate dependencies ahead of time, as described above, without needing to do this on each cold start. This results in a zip file laid out in the format recommended by AWS, and includes a re-export of the handler at the path `lambda_function.handler`.
- In Pants 2.18, the new behaviour will become the default behaviour.
- In Pants 2.19, the old Lambdex behaviour will be entirely removed.

Any existing `python_awslambda` targets will change how they are built. Migrating has three steps:

1. opt-in to the new behaviour in Pants 2.17
2. package the new targets
3. upload those packages to AWS, and update the configured handler from `lambdex_handler.handler` (old) to `lambda_function.handler` (new)

To opt-in to the new behaviour in Pants 2.17, add the following to the end of your `pants.toml`:

``` toml pants.toml
[lambdex]
layout = "zip"
```

To temporarily continue using the old behaviour in Pants 2.17, instead set `layout = "lambdex"`. This will not be supported in Pants 2.19. If you encounter a bug with `layout = "zip"`, [please let us know](https://github.com/pantsbuild/pants/issues/new/choose). If you require advanced PEX features, [switch to using `pex_binary` directly](#advanced-using-pex-directly).
