---
title: "AWS Lambda"
slug: "awslambda-python"
excerpt: "Create a Lambda with Python code."
hidden: false
createdAt: "2020-05-05T16:51:03.851Z"
updatedAt: "2022-05-12T16:58:25.667Z"
---
Pants can create a Lambda-compatible zip file from your Python code, allowing you to develop your Lambdas in your repository instead of using the online Cloud9 editor.

> 📘 FYI: how Pants does this
> 
> Under-the-hood, Pants uses the [Lambdex](https://github.com/pantsbuild/lambdex) project. First, Pants will convert your code into a [Pex file](doc:pex-files). Then, Pants will use Lambdex to convert the Pex into a zip file understood by AWS.

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
$ pants package project/awslambda_example.py
Wrote code bundle to dist/project.zip
  Runtime: python3.8
  Handler: lambdex_handler.handler
```

> 🚧 Running from macOS and failing to build?
> 
> AWS Lambdas must run on Linux, so Pants tells PEX and Pip to build for Linux when resolving your third party dependencies. This means that you can only use pre-built [wheels](https://packaging.python.org/glossary/#term-wheel) (bdists). If your project requires any source distributions ([sdists](https://packaging.python.org/glossary/#term-source-distribution-or-sdist)) that must be built locally, PEX and pip will fail to run.
> 
> If this happens, you must either change your dependencies to only use dependencies with pre-built [wheels](https://pythonwheels.com) or find a Linux environment to run `pants package`.

Step 4: Upload to AWS
---------------------

You can use any of the various AWS methods to upload your zip file, such as the AWS console or the AWS CLI via `aws lambda create-function` and `aws lambda update-function-code`.

You must specify the AWS lambda handler as `lambdex_handler.handler`.

Docker Integration
------------------

To [deploy a Python lambda function with container images](https://docs.aws.amazon.com/lambda/latest/dg/python-image.html), you can use Pants's [Docker](doc:docker) support.

For example:

```dockerfile project/Dockerfile
FROM public.ecr.aws/lambda/python:3.8

RUN yum install unzip -y
COPY project/lambda.zip .
RUN unzip lambda.zip -d "${LAMBDA_TASK_ROOT}"
CMD ["lambdex_handler.handler"]
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
