---
title: "Global options"
slug: "reference-global"
hidden: false
createdAt: "2022-06-02T21:09:10.510Z"
updatedAt: "2022-06-02T21:09:11.172Z"
---
Options to control the overall behavior of Pants.

Backend: <span style="color: purple"><code>pants.core</code></span>
Config section: <span style="color: purple"><code>[GLOBAL]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>level</code></h3>
  <code>-l=&lt;LogLevel&gt;, --level=&lt;LogLevel&gt;</code><br>
  <code>PANTS_LEVEL</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">one of: <code>trace, debug, info, warn, error</code></span><br>
<span style="color: green">default: <code>info</code></span>

<br>

Set the logging level.
</div>
<br>

<div style="color: purple">
  <h3><code>spec_files</code></h3>
  <code>--spec-files=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_SPEC_FILES</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Read additional specs (target addresses, files, and/or globs), one per line, from these files.
</div>
<br>

<div style="color: purple">
  <h3><code>pantsd</code></h3>
  <code>--[no-]pantsd</code><br>
  <code>PANTS_PANTSD</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

Enables use of the Pants daemon (pantsd). pantsd can significantly improve runtime performance by lowering per-run startup cost, and by memoizing filesystem operations and rule execution.
</div>
<br>

<div style="color: purple">
  <h3><code>concurrent</code></h3>
  <code>--[no-]concurrent</code><br>
  <code>PANTS_CONCURRENT</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Enable concurrent runs of Pants. Without this enabled, Pants will start up all concurrent invocations (e.g. in other terminals) without pantsd. Enabling this option requires parallel Pants invocations to block on the first.
</div>
<br>

<div style="color: purple">
  <h3><code>local_cache</code></h3>
  <code>--[no-]local-cache</code><br>
  <code>PANTS_LOCAL_CACHE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

Whether to cache process executions in a local cache persisted to disk at `--local-store-dir`.
</div>
<br>

<div style="color: purple">
  <h3><code>process_cleanup</code></h3>
  <code>--[no-]process-cleanup</code><br>
  <code>PANTS_PROCESS_CLEANUP</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

If false, Pants will not clean up local directories used as chroots for running processes. Pants will log their location so that you can inspect the chroot, and run the `__run.sh` script to recreate the process using the same argv and environment variables used by Pants. This option is useful for debugging.
</div>
<br>

<div style="color: purple">
  <h3><code>remote_execution</code></h3>
  <code>--[no-]remote-execution</code><br>
  <code>PANTS_REMOTE_EXECUTION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Enables remote workers for increased parallelism. (Alpha)

Alternatively, you can use `--remote-cache-read` and `--remote-cache-write` to still run everything locally, but to use a remote cache.
</div>
<br>

<div style="color: purple">
  <h3><code>remote_cache_read</code></h3>
  <code>--[no-]remote-cache-read</code><br>
  <code>PANTS_REMOTE_CACHE_READ</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Whether to enable reading from a remote cache.

This cannot be used at the same time as `--remote-execution`.
</div>
<br>

<div style="color: purple">
  <h3><code>remote_cache_write</code></h3>
  <code>--[no-]remote-cache-write</code><br>
  <code>PANTS_REMOTE_CACHE_WRITE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Whether to enable writing results to a remote cache.

This cannot be used at the same time as `--remote-execution`.
</div>
<br>

<div style="color: purple">
  <h3><code>colors</code></h3>
  <code>--[no-]colors</code><br>
  <code>PANTS_COLORS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Whether Pants should use colors in output or not. This may also impact whether some tools Pants runs use color.

When unset, this value defaults based on whether the output destination supports color.
</div>
<br>

<div style="color: purple">
  <h3><code>dynamic_ui</code></h3>
  <code>--[no-]dynamic-ui</code><br>
  <code>PANTS_DYNAMIC_UI</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Display a dynamically-updating console UI as Pants runs. This is true by default if Pants detects a TTY and there is no 'CI' environment variable indicating that Pants is running in a continuous integration environment.
</div>
<br>

<div style="color: purple">
  <h3><code>dynamic_ui_renderer</code></h3>
  <code>--dynamic-ui-renderer=&lt;DynamicUIRenderer&gt;</code><br>
  <code>PANTS_DYNAMIC_UI_RENDERER</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">one of: <code>indicatif-spinner, experimental-prodash</code></span><br>
<span style="color: green">default: <code>indicatif-spinner</code></span>

<br>

If `--dynamic-ui` is enabled, selects the renderer.
</div>
<br>

<div style="color: purple">
  <h3><code>tag</code></h3>
  <code>--tag=&quot;[[+-]tag1,tag2,..., [+-]tag1,tag2,..., ...]&quot;</code><br>
  <code>PANTS_TAG</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Include only targets with these tags (optional '+' prefix) or without these tags ('-' prefix). See [Advanced target selection](doc:advanced-target-selection).
</div>
<br>

<div style="color: purple">
  <h3><code>exclude_target_regexp</code></h3>
  <code>--exclude-target-regexp=&quot;[&lt;regexp&gt;, &lt;regexp&gt;, ...]&quot;</code><br>
  <code>PANTS_EXCLUDE_TARGET_REGEXP</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Exclude targets that match these regexes. This does not impact file arguments.
</div>
<br>

<div style="color: purple">
  <h3><code>loop</code></h3>
  <code>--[no-]loop</code><br>
  <code>PANTS_LOOP</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Run goals continuously as file changes are detected.
</div>
<br>


## Advanced options

<div style="color: purple">
  <h3><code>backend_packages</code></h3>
  <code>--backend-packages=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_BACKEND_PACKAGES</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Register functionality from these backends.

The backend packages must be present on the PYTHONPATH, typically because they are in the Pants core dist, in a plugin dist, or available as sources in the repo.
</div>
<br>

<div style="color: purple">
  <h3><code>plugins</code></h3>
  <code>--plugins=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_PLUGINS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Allow backends to be loaded from these plugins (usually released through PyPI). The default backends for each plugin will be loaded automatically. Other backends in a plugin can be loaded by listing them in `backend_packages` in the `[GLOBAL]` scope.
</div>
<br>

<div style="color: purple">
  <h3><code>plugins_force_resolve</code></h3>
  <code>--[no-]plugins-force-resolve</code><br>
  <code>PANTS_PLUGINS_FORCE_RESOLVE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Re-resolve plugins, even if previously resolved.
</div>
<br>

<div style="color: purple">
  <h3><code>show_log_target</code></h3>
  <code>--[no-]show-log-target</code><br>
  <code>PANTS_SHOW_LOG_TARGET</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Display the target where a log message originates in that log message's output. This can be helpful when paired with --log-levels-by-target.
</div>
<br>

<div style="color: purple">
  <h3><code>log_levels_by_target</code></h3>
  <code>--log-levels-by-target=&quot;{'key1': val1, 'key2': val2, ...}&quot;</code><br>
  <code>PANTS_LOG_LEVELS_BY_TARGET</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>{}</code></span>

<br>

Set a more specific logging level for one or more logging targets. The names of logging targets are specified in log strings when the --show-log-target option is set. The logging levels are one of: "error", "warn", "info", "debug", "trace". All logging targets not specified here use the global log level set with --level. For example, you can set `--log-levels-by-target='{"workunit_store": "info", "pants.engine.rules": "warn"}'`.
</div>
<br>

<div style="color: purple">
  <h3><code>log_show_rust_3rdparty</code></h3>
  <code>--[no-]log-show-rust-3rdparty</code><br>
  <code>PANTS_LOG_SHOW_RUST_3RDPARTY</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Whether to show/hide logging done by 3rdparty Rust crates used by the Pants engine.
</div>
<br>

<div style="color: purple">
  <h3><code>ignore_warnings</code></h3>
  <code>--ignore-warnings=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_IGNORE_WARNINGS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Ignore logs and warnings matching these strings.

Normally, Pants will look for literal matches from the start of the log/warning message, but you can prefix the ignore with `$regex$` for Pants to instead treat your string as a regex pattern. For example:

    ignore_warnings = [
        "DEPRECATED: option 'config' in scope 'flake8' will be removed",
        '$regex$:No files\s*'
    ]
</div>
<br>

<div style="color: purple">
  <h3><code>pants_version</code></h3>
  <code>--pants-version=&lt;str&gt;</code><br>
  <code>PANTS_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>2.12.0rc2</code></span>

<br>

Use this Pants version. Note that Pants only uses this to verify that you are using the requested version, as Pants cannot dynamically change the version it is using once the program is already running.

If you use the `./pants` script from [Installing Pants](doc:installation), however, changing the value in your `pants.toml` will cause the new version to be installed and run automatically.

Run `./pants --version` to check what is being used.
</div>
<br>

<div style="color: purple">
  <h3><code>pants_bin_name</code></h3>
  <code>--pants-bin-name=&lt;str&gt;</code><br>
  <code>PANTS_BIN_NAME</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>./pants</code></span>

<br>

The name of the script or binary used to invoke Pants. Useful when printing help messages.
</div>
<br>

<div style="color: purple">
  <h3><code>pants_workdir</code></h3>
  <code>--pants-workdir=&lt;dir&gt;</code><br>
  <code>PANTS_WORKDIR</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>&lt;buildroot&gt;/.pants.d</code></span>

<br>

Write intermediate logs and output files to this dir.
</div>
<br>

<div style="color: purple">
  <h3><code>pants_physical_workdir_base</code></h3>
  <code>--pants-physical-workdir-base=&lt;dir&gt;</code><br>
  <code>PANTS_PHYSICAL_WORKDIR_BASE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

When set, a base directory in which to store `--pants-workdir` contents. If this option is a set, the workdir will be created as symlink into a per-workspace subdirectory.
</div>
<br>

<div style="color: purple">
  <h3><code>pants_distdir</code></h3>
  <code>--pants-distdir=&lt;dir&gt;</code><br>
  <code>PANTS_DISTDIR</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>&lt;buildroot&gt;/dist</code></span>

<br>

Write end products, such as the results of `./pants package`, to this dir.
</div>
<br>

<div style="color: purple">
  <h3><code>pants_subprocessdir</code></h3>
  <code>--pants-subprocessdir=&lt;str&gt;</code><br>
  <code>PANTS_SUBPROCESSDIR</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>&lt;buildroot&gt;/.pids</code></span>

<br>

The directory to use for tracking subprocess metadata. This should live outside of the dir used by `pants_workdir` to allow for tracking subprocesses that outlive the workdir data.
</div>
<br>

<div style="color: purple">
  <h3><code>pants_config_files</code></h3>
  <code>--pants-config-files=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_CONFIG_FILES</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "&lt;buildroot&gt;/pants.toml"
]</pre></span>

<br>

Paths to Pants config files. This may only be set through the environment variable `PANTS_CONFIG_FILES` and the command line argument `--pants-config-files`; it will be ignored if in a config file like `pants.toml`.
</div>
<br>

<div style="color: purple">
  <h3><code>pantsrc</code></h3>
  <code>--[no-]pantsrc</code><br>
  <code>PANTS_PANTSRC</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

Use pantsrc files located at the paths specified in the global option `pantsrc_files`.
</div>
<br>

<div style="color: purple">
  <h3><code>pantsrc_files</code></h3>
  <code>--pantsrc-files=&quot;[&lt;path&gt;, &lt;path&gt;, ...]&quot;</code><br>
  <code>PANTS_PANTSRC_FILES</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "/etc/pantsrc",
  "~/.pants.rc",
  ".pants.rc"
]</pre></span>

<br>

Override config with values from these files, using syntax matching that of `--pants-config-files`.
</div>
<br>

<div style="color: purple">
  <h3><code>pythonpath</code></h3>
  <code>--pythonpath=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_PYTHONPATH</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Add these directories to PYTHONPATH to search for plugins. This does not impact the PYTHONPATH used by Pants when running your Python code.
</div>
<br>

<div style="color: purple">
  <h3><code>verify_config</code></h3>
  <code>--[no-]verify-config</code><br>
  <code>PANTS_VERIFY_CONFIG</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

Verify that all config file values correspond to known options.
</div>
<br>

<div style="color: purple">
  <h3><code>stats_record_option_scopes</code></h3>
  <code>--stats-record-option-scopes=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_STATS_RECORD_OPTION_SCOPES</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "&ast;"
]</pre></span>

<br>

Option scopes to record in stats on run completion. Options may be selected by joining the scope and the option with a ^ character, i.e. to get option `pantsd` in the GLOBAL scope, you'd pass `GLOBAL^pantsd`. Add a '*' to the list to capture all known scopes.
</div>
<br>

<div style="color: purple">
  <h3><code>pants_ignore</code></h3>
  <code>--pants-ignore=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_IGNORE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  ".&ast;/",
  "/dist/"
]</pre></span>

<br>

Paths to ignore for all filesystem operations performed by pants (e.g. BUILD file scanning, glob matching, etc). Patterns use the gitignore syntax (https://git-scm.com/docs/gitignore). The `pants_distdir` and `pants_workdir` locations are automatically ignored. `pants_ignore` can be used in tandem with `pants_ignore_use_gitignore`; any rules specified here are applied after rules specified in a .gitignore file.
</div>
<br>

<div style="color: purple">
  <h3><code>pants_ignore_use_gitignore</code></h3>
  <code>--[no-]pants-ignore-use-gitignore</code><br>
  <code>PANTS_IGNORE_USE_GITIGNORE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

Make use of a root .gitignore file when determining whether to ignore filesystem operations performed by Pants. If used together with `--pants-ignore`, any exclude/include patterns specified there apply after .gitignore rules.
</div>
<br>

<div style="color: purple">
  <h3><code>logdir</code></h3>
  <code>-d=&lt;dir&gt;, --logdir=&lt;dir&gt;</code><br>
  <code>PANTS_LOGDIR</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

Write logs to files under this directory.
</div>
<br>

<div style="color: purple">
  <h3><code>pantsd_timeout_when_multiple_invocations</code></h3>
  <code>--pantsd-timeout-when-multiple-invocations=&lt;float&gt;</code><br>
  <code>PANTS_PANTSD_TIMEOUT_WHEN_MULTIPLE_INVOCATIONS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>60.0</code></span>

<br>

The maximum amount of time to wait for the invocation to start until raising a timeout exception. Because pantsd currently does not support parallel runs, any prior running Pants command must be finished for the current one to start. To never timeout, use the value -1.
</div>
<br>

<div style="color: purple">
  <h3><code>pantsd_max_memory_usage</code></h3>
  <code>--pantsd-max-memory-usage=&lt;memory_size&gt;</code><br>
  <code>PANTS_PANTSD_MAX_MEMORY_USAGE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>1GiB</code></span>

<br>

The maximum memory usage of the pantsd process.

When the maximum memory is exceeded, the daemon will restart gracefully, although all previous in-memory caching will be lost. Setting too low means that you may miss out on some caching, whereas setting too high may over-consume resources and may result in the operating system killing Pantsd due to memory overconsumption (e.g. via the OOM killer).

You can suffix with `GiB`, `MiB`, `KiB`, or `B` to indicate the unit, e.g. `2GiB` or `2.12GiB`. A bare number will be in bytes.

There is at most one pantsd process per workspace.
</div>
<br>

<div style="color: purple">
  <h3><code>print_stacktrace</code></h3>
  <code>--[no-]print-stacktrace</code><br>
  <code>PANTS_PRINT_STACKTRACE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Print the full exception stack trace for any errors.
</div>
<br>

<div style="color: purple">
  <h3><code>engine_visualize_to</code></h3>
  <code>--engine-visualize-to=&lt;dir_option&gt;</code><br>
  <code>PANTS_ENGINE_VISUALIZE_TO</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

A directory to write execution and rule graphs to as `dot` files. The contents of the directory will be overwritten if any filenames collide.
</div>
<br>

<div style="color: purple">
  <h3><code>pantsd_pailgun_port</code></h3>
  <code>--pantsd-pailgun-port=&lt;int&gt;</code><br>
  <code>PANTS_PANTSD_PAILGUN_PORT</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>0</code></span>

<br>

The port to bind the Pants nailgun server to. Defaults to a random port.
</div>
<br>

<div style="color: purple">
  <h3><code>pantsd_invalidation_globs</code></h3>
  <code>--pantsd-invalidation-globs=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_PANTSD_INVALIDATION_GLOBS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Filesystem events matching any of these globs will trigger a daemon restart. Pants's own code, plugins, and `--pants-config-files` are inherently invalidated.
</div>
<br>

<div style="color: purple">
  <h3><code>rule_threads_core</code></h3>
  <code>--rule-threads-core=&lt;int&gt;</code><br>
  <code>PANTS_RULE_THREADS_CORE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>max(2, #cores/2)</code></span>

<br>

The number of threads to keep active and ready to execute `@rule` logic (see also: `--rule-threads-max`).

Values less than 2 are not currently supported.

This value is independent of the number of processes that may be spawned in parallel locally (controlled by `--process-execution-local-parallelism`).
</div>
<br>

<div style="color: purple">
  <h3><code>rule_threads_max</code></h3>
  <code>--rule-threads-max=&lt;int&gt;</code><br>
  <code>PANTS_RULE_THREADS_MAX</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

The maximum number of threads to use to execute `@rule` logic. Defaults to a small multiple of `--rule-threads-core`.
</div>
<br>

<div style="color: purple">
  <h3><code>local_store_dir</code></h3>
  <code>--local-store-dir=&lt;str&gt;</code><br>
  <code>PANTS_LOCAL_STORE_DIR</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>$XDG&lowbar;CACHE&lowbar;HOME/lmdb&lowbar;store</code></span>

<br>

Directory to use for the local file store, which stores the results of subprocesses run by Pants.

The path may be absolute or relative. If the directory is within the build root, be sure to include it in `--pants-ignore`.
</div>
<br>

<div style="color: purple">
  <h3><code>local_store_shard_count</code></h3>
  <code>--local-store-shard-count=&lt;int&gt;</code><br>
  <code>PANTS_LOCAL_STORE_SHARD_COUNT</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>16</code></span>

<br>

The number of LMDB shards created for the local store. This setting also impacts the maximum size of stored files: see `--local-store-files-max-size-bytes` for more information.

Because LMDB allows only one simultaneous writer per database, the store is split into multiple shards to allow for more concurrent writers. The faster your disks are, the fewer shards you are likely to need for performance.

NB: After changing this value, you will likely want to manually clear the `--local-store-dir` directory to clear the space used by old shard layouts.
</div>
<br>

<div style="color: purple">
  <h3><code>local_store_processes_max_size_bytes</code></h3>
  <code>--local-store-processes-max-size-bytes=&lt;int&gt;</code><br>
  <code>PANTS_LOCAL_STORE_PROCESSES_MAX_SIZE_BYTES</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>16000000000</code></span>

<br>

The maximum size in bytes of the local store containing process cache entries. Stored below `--local-store-dir`.
</div>
<br>

<div style="color: purple">
  <h3><code>local_store_files_max_size_bytes</code></h3>
  <code>--local-store-files-max-size-bytes=&lt;int&gt;</code><br>
  <code>PANTS_LOCAL_STORE_FILES_MAX_SIZE_BYTES</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>256000000000</code></span>

<br>

The maximum size in bytes of the local store containing files. Stored below `--local-store-dir`.

NB: This size value bounds the total size of all files, but (due to sharding of the store on disk) it also bounds the per-file size to (VALUE / `--local-store-shard-count`).

This value doesn't reflect space allocated on disk, or RAM allocated (it may be reflected in VIRT but not RSS). However, the default is lower than you might otherwise choose because macOS creates core dumps that include MMAP'd pages, and setting this too high might cause core dumps to use an unreasonable amount of disk if they are enabled.
</div>
<br>

<div style="color: purple">
  <h3><code>local_store_directories_max_size_bytes</code></h3>
  <code>--local-store-directories-max-size-bytes=&lt;int&gt;</code><br>
  <code>PANTS_LOCAL_STORE_DIRECTORIES_MAX_SIZE_BYTES</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>16000000000</code></span>

<br>

The maximum size in bytes of the local store containing directories. Stored below `--local-store-dir`.
</div>
<br>

<div style="color: purple">
  <h3><code>named_caches_dir</code></h3>
  <code>--named-caches-dir=&lt;str&gt;</code><br>
  <code>PANTS_NAMED_CACHES_DIR</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>$XDG&lowbar;CACHE&lowbar;HOME/named&lowbar;caches</code></span>

<br>

Directory to use for named global caches for tools and processes with trusted, concurrency-safe caches.

The path may be absolute or relative. If the directory is within the build root, be sure to include it in `--pants-ignore`.
</div>
<br>

<div style="color: purple">
  <h3><code>local_execution_root_dir</code></h3>
  <code>--local-execution-root-dir=&lt;str&gt;</code><br>
  <code>PANTS_LOCAL_EXECUTION_ROOT_DIR</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>/var/folders/bg/&lowbar;r10hqp14kjcpv68yzdk5svc0000gn/T</code></span>

<br>

Directory to use for local process execution sandboxing.

The path may be absolute or relative. If the directory is within the build root, be sure to include it in `--pants-ignore`.
</div>
<br>

<div style="color: purple">
  <h3><code>ca_certs_path</code></h3>
  <code>--ca-certs-path=&lt;str&gt;</code><br>
  <code>PANTS_CA_CERTS_PATH</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

Path to a file containing PEM-format CA certificates used for verifying secure connections when downloading files required by a build.
</div>
<br>

<div style="color: purple">
  <h3><code>process_total_child_memory_usage</code></h3>
  <code>--process-total-child-memory-usage=&lt;memory_size&gt;</code><br>
  <code>PANTS_PROCESS_TOTAL_CHILD_MEMORY_USAGE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>1GiB</code></span>

<br>

The maximum memory usage for all child processes.

This value participates in precomputing the pool size of child processes used by `pantsd`. A high value would result in a high number of child processes spawned, potentially overconsuming your resources and triggering the OS' OOM killer. A low value would mean a low number of child processes launched and therefore less paralellism for the tasks that need those processes.

If setting this value, consider also setting a value for the `process-per-child-memory-usage` option too.

You can suffix with `GiB`, `MiB`, `KiB`, or `B` to indicate the unit, e.g. `2GiB` or `2.12GiB`. A bare number will be in bytes.
</div>
<br>

<div style="color: purple">
  <h3><code>process_per_child_memory_usage</code></h3>
  <code>--process-per-child-memory-usage=&lt;memory_size&gt;</code><br>
  <code>PANTS_PROCESS_PER_CHILD_MEMORY_USAGE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>512MiB</code></span>

<br>

The default memory usage for a child process.

Check the documentation for the `process-total-child-memory-usage` for advice on how to choose an appropriate value for this option.

You can suffix with `GiB`, `MiB`, `KiB`, or `B` to indicate the unit, e.g. `2GiB` or `2.12GiB`. A bare number will be in bytes.
</div>
<br>

<div style="color: purple">
  <h3><code>process_execution_local_parallelism</code></h3>
  <code>--process-execution-local-parallelism=&lt;int&gt;</code><br>
  <code>PANTS_PROCESS_EXECUTION_LOCAL_PARALLELISM</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>#cores</code></span>

<br>

Number of concurrent processes that may be executed locally.

This value is independent of the number of threads that may be used to execute the logic in `@rules` (controlled by `--rule-threads-core`).
</div>
<br>

<div style="color: purple">
  <h3><code>process_execution_remote_parallelism</code></h3>
  <code>--process-execution-remote-parallelism=&lt;int&gt;</code><br>
  <code>PANTS_PROCESS_EXECUTION_REMOTE_PARALLELISM</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>128</code></span>

<br>

Number of concurrent processes that may be executed remotely.
</div>
<br>

<div style="color: purple">
  <h3><code>process_execution_cache_namespace</code></h3>
  <code>--process-execution-cache-namespace=&lt;str&gt;</code><br>
  <code>PANTS_PROCESS_EXECUTION_CACHE_NAMESPACE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

The cache namespace for process execution. Change this value to invalidate every artifact's execution, or to prevent process cache entries from being (re)used for different usecases or users.
</div>
<br>

<div style="color: purple">
  <h3><code>process_execution_local_enable_nailgun</code></h3>
  <code>--[no-]process-execution-local-enable-nailgun</code><br>
  <code>PANTS_PROCESS_EXECUTION_LOCAL_ENABLE_NAILGUN</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

Whether or not to use nailgun to run JVM requests that are marked as supporting nailgun.
</div>
<br>

<div style="color: purple">
  <h3><code>remote_instance_name</code></h3>
  <code>--remote-instance-name=&lt;str&gt;</code><br>
  <code>PANTS_REMOTE_INSTANCE_NAME</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

Name of the remote instance to use by remote caching and remote execution.

This is used by some remote servers for routing. Consult your remote server for whether this should be set.

You can also use `--remote-auth-plugin` to provide a plugin to dynamically set this value.
</div>
<br>

<div style="color: purple">
  <h3><code>remote_ca_certs_path</code></h3>
  <code>--remote-ca-certs-path=&lt;str&gt;</code><br>
  <code>PANTS_REMOTE_CA_CERTS_PATH</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

Path to a PEM file containing CA certificates used for verifying secure connections to `--remote-execution-address` and `--remote-store-address`.

If unspecified, Pants will attempt to auto-discover root CA certificates when TLS is enabled with remote execution and caching.
</div>
<br>

<div style="color: purple">
  <h3><code>remote_oauth_bearer_token_path</code></h3>
  <code>--remote-oauth-bearer-token-path=&lt;str&gt;</code><br>
  <code>PANTS_REMOTE_OAUTH_BEARER_TOKEN_PATH</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

Path to a file containing an oauth token to use for gGRPC connections to `--remote-execution-address` and `--remote-store-address`.

If specified, Pants will add a header in the format `authorization: Bearer <token>`. You can also manually add this header via `--remote-execution-headers` and `--remote-store-headers`, or use `--remote-auth-plugin` to provide a plugin to dynamically set the relevant headers. Otherwise, no authorization will be performed.
</div>
<br>

<div style="color: purple">
  <h3><code>remote_auth_plugin</code></h3>
  <code>--remote-auth-plugin=&lt;str&gt;</code><br>
  <code>PANTS_REMOTE_AUTH_PLUGIN</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

Path to a plugin to dynamically configure remote caching and execution options.

Format: `path.to.module:my_func`. Pants will import your module and run your function. Update the `--pythonpath` option to ensure your file is loadable.

The function should take the kwargs `initial_store_headers: dict[str, str]`, `initial_execution_headers: dict[str, str]`, `options: Options` (from pants.option.options), `env: dict[str, str]`, and `prior_result: AuthPluginResult | None`. It should return an instance of `AuthPluginResult` from `pants.option.global_options`.

Pants will replace the headers it would normally use with whatever your plugin returns; usually, you should include the `initial_store_headers` and `initial_execution_headers` in your result so that options like `--remote-store-headers` still work.

If you return `instance_name`, Pants will replace `--remote-instance-name` with this value.

If the returned auth state is `AuthPluginState.UNAVAILABLE`, Pants will disable remote caching and execution.

If Pantsd is in use, `prior_result` will be the previous `AuthPluginResult` returned by your plugin, which allows you to reuse the result. Otherwise, if Pantsd has been restarted or is not used, the `prior_result` will be `None`.
</div>
<br>

<div style="color: purple">
  <h3><code>remote_store_address</code></h3>
  <code>--remote-store-address=&lt;str&gt;</code><br>
  <code>PANTS_REMOTE_STORE_ADDRESS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

The URI of a server used for the remote file store.

Format: `scheme://host:port`. The supported schemes are `grpc` and `grpcs`, i.e. gRPC with TLS enabled. If `grpc` is used, TLS will be disabled.
</div>
<br>

<div style="color: purple">
  <h3><code>remote_store_headers</code></h3>
  <code>--remote-store-headers=&quot;{'key1': val1, 'key2': val2, ...}&quot;</code><br>
  <code>PANTS_REMOTE_STORE_HEADERS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>{
  "user-agent": "pants/2.12.0rc2"
}</pre></span>

<br>

Headers to set on remote store requests.

Format: header=value. Pants may add additional headers.

See `--remote-execution-headers` as well.
</div>
<br>

<div style="color: purple">
  <h3><code>remote_store_chunk_bytes</code></h3>
  <code>--remote-store-chunk-bytes=&lt;int&gt;</code><br>
  <code>PANTS_REMOTE_STORE_CHUNK_BYTES</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>1048576</code></span>

<br>

Size in bytes of chunks transferred to/from the remote file store.
</div>
<br>

<div style="color: purple">
  <h3><code>remote_store_chunk_upload_timeout_seconds</code></h3>
  <code>--remote-store-chunk-upload-timeout-seconds=&lt;int&gt;</code><br>
  <code>PANTS_REMOTE_STORE_CHUNK_UPLOAD_TIMEOUT_SECONDS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>60</code></span>

<br>

Timeout (in seconds) for uploads of individual chunks to the remote file store.
</div>
<br>

<div style="color: purple">
  <h3><code>remote_store_rpc_retries</code></h3>
  <code>--remote-store-rpc-retries=&lt;int&gt;</code><br>
  <code>PANTS_REMOTE_STORE_RPC_RETRIES</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>2</code></span>

<br>

Number of times to retry any RPC to the remote store before giving up.
</div>
<br>

<div style="color: purple">
  <h3><code>remote_store_rpc_concurrency</code></h3>
  <code>--remote-store-rpc-concurrency=&lt;int&gt;</code><br>
  <code>PANTS_REMOTE_STORE_RPC_CONCURRENCY</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>128</code></span>

<br>

The number of concurrent requests allowed to the remote store service.
</div>
<br>

<div style="color: purple">
  <h3><code>remote_store_batch_api_size_limit</code></h3>
  <code>--remote-store-batch-api-size-limit=&lt;int&gt;</code><br>
  <code>PANTS_REMOTE_STORE_BATCH_API_SIZE_LIMIT</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>4194304</code></span>

<br>

The maximum total size of blobs allowed to be sent in a single batch API call to the remote store.
</div>
<br>

<div style="color: purple">
  <h3><code>remote_cache_warnings</code></h3>
  <code>--remote-cache-warnings=&lt;RemoteCacheWarningsBehavior&gt;</code><br>
  <code>PANTS_REMOTE_CACHE_WARNINGS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">one of: <code>ignore, first_only, backoff</code></span><br>
<span style="color: green">default: <code>first&lowbar;only</code></span>

<br>

Whether to log remote cache failures at the `warn` log level.

All errors not logged at the `warn` level will instead be logged at the `debug` level.
</div>
<br>

<div style="color: purple">
  <h3><code>remote_cache_eager_fetch</code></h3>
  <code>--[no-]remote-cache-eager-fetch</code><br>
  <code>PANTS_REMOTE_CACHE_EAGER_FETCH</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

Eagerly fetch relevant content from the remote store instead of lazily fetching.

This may result in worse performance, but reduce the frequency of errors encountered by reducing the surface area of when remote caching is used.
</div>
<br>

<div style="color: purple">
  <h3><code>remote_cache_rpc_concurrency</code></h3>
  <code>--remote-cache-rpc-concurrency=&lt;int&gt;</code><br>
  <code>PANTS_REMOTE_CACHE_RPC_CONCURRENCY</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>128</code></span>

<br>

The number of concurrent requests allowed to the remote cache service.
</div>
<br>

<div style="color: purple">
  <h3><code>remote_cache_read_timeout_millis</code></h3>
  <code>--remote-cache-read-timeout-millis=&lt;int&gt;</code><br>
  <code>PANTS_REMOTE_CACHE_READ_TIMEOUT_MILLIS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>1500</code></span>

<br>

Timeout value for remote cache lookups in milliseconds.
</div>
<br>

<div style="color: purple">
  <h3><code>remote_execution_address</code></h3>
  <code>--remote-execution-address=&lt;str&gt;</code><br>
  <code>PANTS_REMOTE_EXECUTION_ADDRESS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>None</code></span>

<br>

The URI of a server used as a remote execution scheduler.

Format: `scheme://host:port`. The supported schemes are `grpc` and `grpcs`, i.e. gRPC with TLS enabled. If `grpc` is used, TLS will be disabled.

You must also set `--remote-store-address`, which will often be the same value.
</div>
<br>

<div style="color: purple">
  <h3><code>remote_execution_extra_platform_properties</code></h3>
  <code>--remote-execution-extra-platform-properties=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_REMOTE_EXECUTION_EXTRA_PLATFORM_PROPERTIES</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Platform properties to set on remote execution requests. Format: property=value. Multiple values should be specified as multiple occurrences of this flag. Pants itself may add additional platform properties.
</div>
<br>

<div style="color: purple">
  <h3><code>remote_execution_headers</code></h3>
  <code>--remote-execution-headers=&quot;{'key1': val1, 'key2': val2, ...}&quot;</code><br>
  <code>PANTS_REMOTE_EXECUTION_HEADERS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>{
  "user-agent": "pants/2.12.0rc2"
}</pre></span>

<br>

Headers to set on remote execution requests. Format: header=value. Pants may add additional headers.

See `--remote-store-headers` as well.
</div>
<br>

<div style="color: purple">
  <h3><code>remote_execution_overall_deadline_secs</code></h3>
  <code>--remote-execution-overall-deadline-secs=&lt;int&gt;</code><br>
  <code>PANTS_REMOTE_EXECUTION_OVERALL_DEADLINE_SECS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>3600</code></span>

<br>

Overall timeout in seconds for each remote execution request from time of submission
</div>
<br>

<div style="color: purple">
  <h3><code>remote_execution_rpc_concurrency</code></h3>
  <code>--remote-execution-rpc-concurrency=&lt;int&gt;</code><br>
  <code>PANTS_REMOTE_EXECUTION_RPC_CONCURRENCY</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>128</code></span>

<br>

The number of concurrent requests allowed to the remote execution service.
</div>
<br>

<div style="color: purple">
  <h3><code>watch_filesystem</code></h3>
  <code>--[no-]watch-filesystem</code><br>
  <code>PANTS_WATCH_FILESYSTEM</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

Set to False if Pants should not watch the filesystem for changes. `pantsd` or `loop` may not be enabled.
</div>
<br>

<div style="color: purple">
  <h3><code>files_not_found_behavior</code></h3>
  <code>--files-not-found-behavior=&lt;FilesNotFoundBehavior&gt;</code><br>
  <code>PANTS_FILES_NOT_FOUND_BEHAVIOR</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">one of: <code>warn, error</code></span><br>
<span style="color: green">default: <code>warn</code></span>

<br>

What to do when files and globs specified in BUILD files, such as in the `sources` field, cannot be found. This happens when the files do not exist on your machine or when they are ignored by the `--pants-ignore` option.
</div>
<br>

<div style="color: purple">
  <h3><code>owners_not_found_behavior</code></h3>
  <code>--owners-not-found-behavior=&lt;OwnersNotFoundBehavior&gt;</code><br>
  <code>PANTS_OWNERS_NOT_FOUND_BEHAVIOR</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">one of: <code>ignore, warn, error</code></span><br>
<span style="color: green">default: <code>error</code></span>

<br>

What to do when file arguments do not have any owning target. This happens when there are no targets whose `sources` fields include the file argument.
</div>
<br>

<div style="color: purple">
  <h3><code>build_patterns</code></h3>
  <code>--build-patterns=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_BUILD_PATTERNS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "BUILD",
  "BUILD.&ast;"
]</pre></span>

<br>

The naming scheme for BUILD files, i.e. where you define targets.

This only sets the naming scheme, not the directory paths to look for. To add ignore patterns, use the option `[GLOBAL].build_ignore`.

You may also need to update the option `[tailor].build_file_name` so that it is compatible with this option.
</div>
<br>

<div style="color: purple">
  <h3><code>build_ignore</code></h3>
  <code>--build-ignore=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_BUILD_IGNORE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Path globs or literals to ignore when identifying BUILD files.

This does not affect any other filesystem operations; use `--pants-ignore` for that instead.
</div>
<br>

<div style="color: purple">
  <h3><code>build_file_prelude_globs</code></h3>
  <code>--build-file-prelude-globs=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_BUILD_FILE_PRELUDE_GLOBS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Python files to evaluate and whose symbols should be exposed to all BUILD files. See [Macros](doc:macros).
</div>
<br>

<div style="color: purple">
  <h3><code>subproject_roots</code></h3>
  <code>--subproject-roots=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_SUBPROJECT_ROOTS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Paths that correspond with build roots for any subproject that this project depends on.
</div>
<br>

<div style="color: purple">
  <h3><code>loop_max</code></h3>
  <code>--loop-max=&lt;int&gt;</code><br>
  <code>PANTS_LOOP_MAX</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>4294967296</code></span>

<br>

The maximum number of times to loop when `--loop` is specified.
</div>
<br>

<div style="color: purple">
  <h3><code>streaming_workunits_report_interval</code></h3>
  <code>--streaming-workunits-report-interval=&lt;float&gt;</code><br>
  <code>PANTS_STREAMING_WORKUNITS_REPORT_INTERVAL</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>1.0</code></span>

<br>

Interval in seconds between when streaming workunit event receivers will be polled.
</div>
<br>

<div style="color: purple">
  <h3><code>streaming_workunits_level</code></h3>
  <code>--streaming-workunits-level=&lt;LogLevel&gt;</code><br>
  <code>PANTS_STREAMING_WORKUNITS_LEVEL</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">one of: <code>trace, debug, info, warn, error</code></span><br>
<span style="color: green">default: <code>debug</code></span>

<br>

The level of workunits that will be reported to streaming workunit event receivers.

Workunits form a tree, and even when workunits are filtered out by this setting, the workunit tree structure will be preserved (by adjusting the parent pointers of the remaining workunits).
</div>
<br>

<div style="color: purple">
  <h3><code>streaming_workunits_complete_async</code></h3>
  <code>--[no-]streaming-workunits-complete-async</code><br>
  <code>PANTS_STREAMING_WORKUNITS_COMPLETE_ASYNC</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>True</code></span>

<br>

True if stats recording should be allowed to complete asynchronously when `pantsd` is enabled. When `pantsd` is disabled, stats recording is always synchronous. To reduce data loss, this flag defaults to false inside of containers, such as when run with Docker.
</div>
<br>


## Deprecated options

None