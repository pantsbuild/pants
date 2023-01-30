---
title: "Google Cloud Functions"
slug: "google-cloud-function-python"
excerpt: "Create a Cloud Function with Python."
hidden: false
createdAt: "2021-11-09T20:29:58.330Z"
updatedAt: "2022-01-29T16:47:46.951Z"
---
Pants can create a Google Cloud Function-compatible zip file from your Python code, allowing you to develop your functions in your repository.

> 📘 FYI: how Pants does this
> 
> Under-the-hood, Pants uses the [Lambdex](https://github.com/pantsbuild/lambdex) project. First, Pants will convert your code into a [Pex file](doc:pex-files). Then, Pants will use Lambdex to convert the Pex into a zip file understood by Google Cloud Functions.

Step 1: Activate the Python Google Cloud Function backend
---------------------------------------------------------

Add this to your `pants.toml`:

```toml pants.toml
[GLOBAL]
backend_packages.add = [
  "pants.backend.google_cloud_function.python",
  "pants.backend.python",
]
```

This adds the new `python_google_cloud_function` target, which you can confirm by running `pants help python_google_cloud_function `

Step 2: Define a `python_google_cloud_function ` target
-------------------------------------------------------

First, add your Cloud function in a Python file like you would [normally do with Google Cloud Functions](https://cloud.google.com/functions/docs/first-python), such as creating a function `def my_handler_name(event, context)` for event-based functions.

Then, in your BUILD file, make sure that you have a `python_source` or `python_sources` target with the handler file included in the `sources` field. You can use [`pants tailor ::`](doc:initial-configuration#5-generate-build-files) to automate this.

Add a `python_google_cloud_function` target and define the `runtime`, `handler`, and `type` fields. The `type` should be either `"event"` or `"http"`. The `runtime` should be one of the values from <https://cloud.google.com/functions/docs/concepts/python-runtime>. The `handler` has the form `handler_file.py:handler_func`, which Pants will convert into a well-formed entry point. Alternatively, you can set `handler` to the format `path.to.module:handler_func`.

For example:

```python project/BUILD
# The default `sources` field will include our handler file.
python_sources(name="lib")

python_google_cloud_function(
    name="cloud_function",
    runtime="python38",
    # Pants will convert this to `project.lambda_example:example_handler`.
    handler="google_cloud_function_example.py:example_handler",
    type="event",
)
```
```python project/google_cloud_function_example.py
def example_handler(event, context):
    print("Hello Google Cloud Function!")
```

Pants will use [dependency inference](doc:targets) based on the `handler` field, which you can confirm by running `pants dependencies path/to:cloud_function`. You can also manually add to the `dependencies` field.

You can optionally set the `output_path` field to change the generated zip file's path.

> 🚧 Use `resource` instead of `file`
> 
> `file` / `files` targets will not be included in the built Cloud Function because filesystem APIs like `open()` would not load them as expected. Instead, use the `resource` / `resources` target. See [Assets and archives](doc:assets) for further explanation.

Step 3: Run `package`
---------------------

Now run `pants package` on your `python_google_cloud_function` target to create a zipped file. 

For example:

```bash
$ pants package project/google_cloud_function_example.py
Wrote code bundle to dist/project.zip
  Runtime: python3.8
  Handler: handler
```

> 🚧 Running from macOS and failing to build?
> 
> Cloud Functions must run on Linux, so Pants tells PEX and Pip to build for Linux when resolving your third party dependencies. This means that you can only use pre-built [wheels](https://packaging.python.org/glossary/#term-wheel) (bdists). If your project requires any source distributions ([sdists](https://packaging.python.org/glossary/#term-source-distribution-or-sdist)) that must be built locally, PEX and pip will fail to run.
> 
> If this happens, you must either change your dependencies to only use dependencies with pre-built [wheels](https://pythonwheels.com) or find a Linux environment to run `pants package`.

Step 4: Upload to Google Cloud
------------------------------

You can use any of the various Google Cloud methods to upload your zip file, such as the Google Cloud console or the [Google Cloud CLI](https://cloud.google.com/functions/docs/deploying/filesystem#deploy_using_the_gcloud_tool).

You must specify the handler as `handler`.
