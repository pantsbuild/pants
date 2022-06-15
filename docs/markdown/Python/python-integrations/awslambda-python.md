---
title: "AWS Lambda"
slug: "awslambda-python"
excerpt: "Create a Lambda with Python code."
hidden: false
createdAt: "2020-05-05T16:51:03.851Z"
updatedAt: "2022-05-12T16:58:25.667Z"
---
Pants can create a Lambda-compatible zip file from your Python code, allowing you to develop your Lambdas in your repository instead of using the online Cloud9 editor.
[block:callout]
{
  "type": "info",
  "title": "FYI: how Pants does this",
  "body": "Under-the-hood, Pants uses the [Lambdex](https://github.com/pantsbuild/lambdex) project. First, Pants will convert your code into a [Pex file](doc:pex-files). Then, Pants will use Lambdex to convert the Pex into a zip file understood by AWS."
}
[/block]

[block:api-header]
{
  "title": "Step 1: Activate the Python AWS Lambda backend"
}
[/block]
Add this to your `pants.toml`:
[block:code]
{
  "codes": [
    {
      "code": "[GLOBAL]\nbackend_packages.add = [\n  \"pants.backend.awslambda.python\",\n  \"pants.backend.python\",\n]",
      "language": "toml",
      "name": "pants.toml"
    }
  ]
}
[/block]
This adds the new `python_awslambda` target, which you can confirm by running `./pants help python_awslambda`
[block:api-header]
{
  "title": "Step 2: Define a `python_awslambda` target"
}
[/block]
First, add your lambda function in a Python file like you would [normally do with AWS Lambda](https://docs.aws.amazon.com/lambda/latest/dg/python-handler.html). Specifically, create a function `def my_handler_name(event, context)` with the name you want.

Then, in your BUILD file, make sure that you have a `python_source` or `python_sources` target with the handler file included in the `sources` field. You can use [`./pants tailor ::`](doc:create-initial-build-files) to automate this.

Add a `python_awslambda` target and define the `runtime` and `handler` fields. The `runtime` should be one of the values from https://docs.aws.amazon.com/lambda/latest/dg/lambda-python.html. The `handler` has the form `handler_file.py:handler_func`, which Pants will convert into a well-formed entry point. Alternatively, you can set `handler` to the format `path.to.module:handler_func`.

For example:
[block:code]
{
  "codes": [
    {
      "code": "# The default `sources` field will include our handler file.\npython_sources(name=\"lib\")\n\npython_awslambda(\n    name=\"lambda\",\n    runtime=\"python3.8\",\n    # Pants will convert this to `project.lambda_example:example_handler`.\n    handler=\"lambda_example.py:example_handler\",\n)",
      "language": "python",
      "name": "project/BUILD"
    },
    {
      "code": "def example_handler(event, context):\n    print(\"Hello AWS!\")",
      "language": "python",
      "name": "project/lambda_example.py"
    }
  ]
}
[/block]
Pants will use [dependency inference](doc:targets) based on the `handler` field, which you can confirm by running `./pants dependencies path/to:lambda`. You can also manually add to the `dependencies` field.

You can optionally set the `output_path` field to change the generated zip file's path.
[block:callout]
{
  "type": "warning",
  "body": "`file` / `files` targets will not be included in the built AWS Lambda because filesystem APIs like `open()` would not load them as expected. Instead, use the `resource` and `resources` target. See [Assets and archives](doc:assets) for further explanation.",
  "title": "Use `resource` instead of `file`"
}
[/block]

[block:api-header]
{
  "title": "Step 3: Run `package`"
}
[/block]
Now run `./pants package` on your `python_awslambda` target to create a zipped file. 

For example:

```bash
$ ./pants package project/awslambda_example.py
Wrote code bundle to dist/project.zip
  Runtime: python3.8
  Handler: lambdex_handler.handler
```
[block:callout]
{
  "type": "warning",
  "title": "Running from macOS and failing to build?",
  "body": "AWS Lambdas must run on Linux, so Pants tells PEX and Pip to build for Linux when resolving your third party dependencies. This means that you can only use pre-built [wheels](https://packaging.python.org/glossary/#term-wheel) (bdists). If your project requires any source distributions ([sdists](https://packaging.python.org/glossary/#term-source-distribution-or-sdist)) that must be built locally, PEX and pip will fail to run.\n\nIf this happens, you must either change your dependencies to only use dependencies with pre-built [wheels](https://pythonwheels.com) or find a Linux environment to run `./pants package`."
}
[/block]

[block:api-header]
{
  "title": "Step 4: Upload to AWS"
}
[/block]
You can use any of the various AWS methods to upload your zip file, such as the AWS console or the AWS CLI via `aws lambda create-function` and `aws lambda update-function-code`.

You must specify the AWS lambda handler as `lambdex_handler.handler`.
[block:api-header]
{
  "title": "Docker Integration"
}
[/block]
To [deploy a Python lambda function with container images](https://docs.aws.amazon.com/lambda/latest/dg/python-image.html), you can use Pants's [Docker](doc:docker) support.

For example:
[block:code]
{
  "codes": [
    {
      "code": "FROM public.ecr.aws/lambda/python:3.8\n\nWORKDIR /build\nRUN yum install unzip -y\nCOPY project/lambda.zip /build\nRUN unzip /build/lambda.zip -d /app\nWORKDIR /app\nCMD [\"/app/lambdex_handler.handler\"]",
      "language": "dockerfile",
      "name": "project/Dockerfile"
    },
    {
      "code": "python_sources()\n\npython_awslambda(\n    name=\"lambda\",\n    runtime=\"python3.8\",\n    handler=\"main.py:lambda_handler\"\n)\n\ndocker_image(\n    name=\"my_image\",\n    dependencies = [\":lambda\"],\n)",
      "language": "python",
      "name": "project/BUILD"
    }
  ]
}
[/block]
Then, use `./pants package project:my_image`, for example. Pants will first build your AWS Lambda, and then will build the Docker image and copy it into the AWS Lambda.