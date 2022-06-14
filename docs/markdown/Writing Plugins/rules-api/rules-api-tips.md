---
title: "Tips and debugging"
slug: "rules-api-tips"
hidden: false
createdAt: "2020-05-08T04:15:06.256Z"
updatedAt: "2022-02-10T19:52:27.560Z"
---
[block:callout]
{
  "type": "info",
  "title": "Reminder: ask for help",
  "body": "We would love to help you with your plugin. Please reach out through [Slack](doc:community).\n\nWe also appreciate any feedback on the Rules API. If you find certain things confusing or are looking for additional mechanisms, please let us know."
}
[/block]

[block:api-header]
{
  "title": "Tip: Use `MultiGet` for increased concurrency"
}
[/block]
Every time your rule has `await`, Python will yield execution to the engine and not resume until the engine returns the result. So, you can improve concurrency by instead bundling multiple `Get` requests into a single `MultiGet`, which will allow each request to be resolved through a separate thread.

Okay:

```python
from pants.core.util_rules.determine_source_files import SourceFilesRequest, SourceFiles
from pants.engine.fs import AddPrefix, Digest
from pants.engine.selectors import Get, MultiGet

@rule
async def demo(...) -> Foo:
    new_digest = await Get(Digest, AddPrefix(original_digest, "new_prefix"))
    source_files = await Get(SourceFiles, SourceFilesRequest(sources_fields))
```

Better:

```python
from pants.core.util_rules.determine_source_files import SourceFilesRequest, SourceFiles
from pants.engine.fs import AddPrefix, Digest
from pants.engine.selectors import Get, MultiGet

@rule
async def demo(...) -> Foo:
    new_digest, source_files = await MultiGet(
        Get(Digest, AddPrefix(original_digest, "new_prefix")),
        Get(SourceFiles, SourceFilesRequest(sources_fields)),
    )
```

[block:api-header]
{
  "title": "Tip: Add logging"
}
[/block]
As explained in [Logging and dynamic output](doc:rules-api-logging), you can add logging to any `@rule` by using Python's `logging` module like you normally would.
[block:api-header]
{
  "title": "FYI: Caching semantics"
}
[/block]
There are two layers to Pants caching: in-memory memoization and caching written to disk via the [LMDB store](https://en.wikipedia.org/wiki/Lightning_Memory-Mapped_Database).

Pants will write to the LMDB store—usually at `~/.cache/pants/lmdb_store`—for any `Process` execution and when ["digesting" files](doc:rules-api-file-system), such as downloading a file or reading from the filesystem. The cache is based on inputs; for example, if the input `Process` is identical to a previous run, then the cache will use the corresponding cached `ProcessResult`. Writing to and reading from LMDB store is very fast, and reads are concurrent. The cache will be occasionally garbage collected by Pantsd, and users may also use `--no-local-cache` or manually delete `~/.cache/pants/lmdb_store`.

Pants will also memoize in-memory the evaluation of all `@rule`s. This means that once a rule runs, if the inputs are identical to a prior run, the cache will be used instead of re-evaluating the rule. If the user uses Pantsd (the Pants daemon), this memoization will persist across distinct Pants runs, until the daemon is shut down or restarted. This memoization happens automatically.
[block:api-header]
{
  "title": "Debugging: Look inside the chroot"
}
[/block]
When Pants runs most processes, it runs in a `chroot` (temporary directory). Usually, this gets cleaned up after the `Process` finishes. You can instead run `./pants --no-process-cleanup`, which will keep around the folder.

Pants will log the path to the chroot, e.g.:

```
▶ ./pants --no-process-cleanup test src/python/pants/util/strutil_test.py
...
12:29:45.08 [INFO] preserving local process execution dir `"/private/var/folders/sx/pdpbqz4x5cscn9hhfpbsbqvm0000gn/T/process-executionN9Kdk0"` for "Test binary /Users/pantsbuild/.pyenv/shims/python3."
...
```

Inside the preserved sandbox there will be a `__run.sh` script which can be used to inspect or re-run the `Process` precisely as Pants did when creating the sandbox.
[block:api-header]
{
  "title": "Debugging: Visualize the rule graph"
}
[/block]
You can create a visual representation of the rule graph through the option `--engine-visualize-to=$dir_path $goal`. This will create the files `rule_graph.dot`, `rule_graph.$goal.dot`, and `graph.000.dot`, which are [`.dot` files](https://en.wikipedia.org/wiki/DOT_%28graph_description_language%29). `rule_graph.$goal.dot` contains only the rules used during your run, `rule_graph.dot` contains all rules, and `graph.000.dot` contains the actual runtime results of all rules (it can be quite large!).

To open up the `.dot` file, you can install the [`graphviz`](https://graphviz.org) program, then run `dot -Tpdf -O $destination`. We recommend opening up the PDF in Google Chrome or OSX Preview, which do a good job of zooming in large PDF files.
[block:api-header]
{
  "title": "Debugging rule graph issues"
}
[/block]
Rule graph issues can be particularly hard to figure out - the error messages are noisy and do not make clear how to fix the issue. We plan to improve this. 

We encourage you to reach out in #plugins on [Slack](doc:getting-help) for help.

Often the best way to debug a rule graph issue is to isolate where the problem comes from by commenting out code until the graph compiles. The rule graph is formed solely by looking at the types in the signature of your `@rule` and in any `Get` statements - none of the rest of your rules matter. To check if the rule graph can be built, simply run `./pants --version`.

We recommend starting by determining which backend—or combination of backends—is causing issues. You can run the below script to find this. Once you find the smallest offending combination, focus on fixing that first by removing all irrelevant backends from `backend_packages` in `pants.toml`—this reduces the surface area of where issues can come from. (You may need to use the option `--no-verify-config` so that Pants doesn't complain about unrecognized options.)
[block:code]
{
  "codes": [
    {
      "code": "#!/usr/bin/env python3\n\nimport itertools\nimport logging\nimport subprocess\n\nBACKENDS = {\n    # Replace this with the backend_packages from your pants.toml.\n    #\n    # Warning: it's easy to get a combinatorial explosion if you \n    # use lots of backends. In that case, try using a subset of your\n    # backends and see if you can still get a rule graph failure.\n    \"pants.backend.python\",\n    \"pants.backend.shell\",\n}\n\n\ndef backends_load(backends) -> bool:\n    logging.info(f\"Testing {backends}\")\n    result = subprocess.run(\n        [\"./pants\", f\"--backend-packages={repr(list(backends))}\", \"--version\"],\n        stdout=subprocess.DEVNULL,\n        stderr=subprocess.DEVNULL,\n    )\n    loads = result.returncode == 0\n    if not loads:\n        logging.error(f\"Failed! {backends}\")\n    return result.returncode == 0\n\n\ndef main() -> None:\n    all_combos = itertools.chain.from_iterable(\n        itertools.combinations(BACKENDS, r=r) for r in range(1, len(BACKENDS) + 1)\n    )\n    bad_combos = {repr(combo) for combo in all_combos if not backends_load(combo)}\n    print(\"----\\nBad combos:\\n\" + \"\\n\".join(bad_combos))\n\n\nif __name__ == \"__main__\":\n    logging.basicConfig(level=logging.INFO, format=\"%(levelname)s: %(message)s\")\n    main()",
      "language": "python",
      "name": "find_bad_backend_combos.py"
    }
  ]
}
[/block]
Once you've identified the smallest combination of backends that fail and you have updated `pants.toml`, you can try isolating which rules are problematic by commenting out `Get`s and the parameters to `@rule`s.

Some common sources of rule graph failures:

* Dependent rules are not registered.
     - This is especially common when you only have one backend activated entirely. We recommend trying to get each backend to be valid regardless of what other backends are activated. Use the above script to see if this is happening.
     - To fix this, see which types you're using in your `@rule` signatures and `Get`s. If they come from another backend, activate their rules. For example, if you use `await Get(Pex, PexRequest)`, you should activate `pants.backend.python.util_rules.pex.rules()` in your `register.py`.
* Not "newtyping".
   - It's possible and sometimes desirable to use types already defined in your plugin or core Pants. For example, you might want to define a new rule that goes from `MyCustomClass -> Process`. However, sometimes this makes the rule graph more complicated than it needs to be.
   - It's often helpful to create a result and request type for each of your `@rule`s, e.g. `MyPlugin` and `MyPluginRequest`.
   - See [Valid types](doc:rules-api-concepts#valid-types) for more.