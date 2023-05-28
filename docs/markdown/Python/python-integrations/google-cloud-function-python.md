---
title: "Google Cloud Functions"
slug: "google-cloud-function-python"
excerpt: "Create a Cloud Function with Python."
hidden: false
createdAt: "2021-11-09T20:29:58.330Z"
---
Pants can create a Google Cloud Function-compatible zip file from your Python code, allowing you to develop your functions in your repository.

> 📘 FYI: how Pants does this
>
> Under-the-hood, Pants uses the [PEX](https://github.com/pantsbuild/pex) project, to select the appropriate third-party requirements and first-party sources and lay them out in a zip file, in the format recommended by Google Cloud Functions.


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

> 🚧 Set `layout = "zip"` for Pants 2.17
>
> Pants 2.17 is transitioning to a new, better layout, but defaults to the old Lambdex layout for backwards compatibility (see [below](#migrating-from-pants-216-and-earlier) for more details). To silence the warnings and be ready for Pants 2.18, add the following to the end of your `pants.toml`
>
> ```toml pants.toml
> [lambdex]
> layout = "zip"
> ```

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
$ pants package project/:cloud_function
Wrote dist/project/cloud_function.zip
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

You must specify the handler as `handler`. This is a re-export of the function referred to by the `handler` field of the target.

Migrating from Pants 2.16 and earlier
-------------------------------------

Pants has implemented a new way to package Google Cloud Functions in 2.17, resulting in smaller packages and faster cold starts. This involves some changes:

- In Pants 2.16 and earlier, Pants used the [Lambdex](https://github.com/pantsbuild/lambdex) project. First, Pants would convert your code into a [Pex file](doc:pex-files) and then use Lambdex to adapt this into a zip file understood by GCF by adding a shim handler. This shim handler first triggers the Pex initialization to choose and unzip dependencies, during initialization.
- In Pants 2.17, the use of Lambdex is deprecated, in favour of choosing the appropriate dependencies ahead of time, as described above, without needing to do this on each cold start. This results in a zip file laid out in the format recommended by GCF, and includes a re-export of the handler.
- In Pants 2.18, the new behaviour will become the default behaviour.
- In Pants 2.19, the old Lambdex behaviour will be entirely removed.

Any existing `python_google_cloud_function` targets will change how they are built. Migrating has three steps:

1. opt-in to the new behaviour in Pants 2.17
2. package the new targets
3. upload those packages to GCF (the existing handler configuration should still work)

To opt-in to the new behaviour in Pants 2.17, set:

``` toml pants.toml
[lambdex]
layout = "zip"
```

To temporarily continue using the old behaviour in Pants 2.17, instead set `layout = "lambdex"`. This will not be supported in Pants 2.19. If you encounter a bug with `layout = "zip"`, [please let us know](https://github.com/pantsbuild/pants/issues/new/choose).
