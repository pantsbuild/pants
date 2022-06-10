---
title: "grpc-python-plugin"
slug: "reference-grpc-python-plugin"
hidden: false
createdAt: "2022-06-02T21:09:45.683Z"
updatedAt: "2022-06-02T21:09:46.095Z"
---
The gRPC Protobuf plugin for Python.

Backend: <span style="color: purple"><code>pants.backend.codegen.protobuf.python</code></span>
Config section: <span style="color: purple"><code>[grpc-python-plugin]</code></span>

## Basic options

None

## Advanced options

<div style="color: purple">
  <h3><code>version</code></h3>
  <code>--grpc-python-plugin-version=&lt;str&gt;</code><br>
  <code>PANTS_GRPC_PYTHON_PLUGIN_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>1.32.0</code></span>

<br>

Use this version of grpcpythonplugin.
</div>
<br>

<div style="color: purple">
  <h3><code>known_versions</code></h3>
  <code>--grpc-python-plugin-known-versions=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_GRPC_PYTHON_PLUGIN_KNOWN_VERSIONS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "1.32.0|macos&lowbar;arm64 |b2db586656463841aa2fd4aab34fb6bd3ef887b522d80e4f2f292146c357f533|6215304",
  "1.32.0|macos&lowbar;x86&lowbar;64|b2db586656463841aa2fd4aab34fb6bd3ef887b522d80e4f2f292146c357f533|6215304",
  "1.32.0|linux&lowbar;arm64 |9365e728c603d64735963074340994245d324712344f63557ef3630864dd9f52|5233664",
  "1.32.0|linux&lowbar;x86&lowbar;64|1af99df9bf733c17a75cbe379f3f9d9ff1627d8a8035ea057c3c78575afe1687|4965728"
]</pre></span>

<br>


Known versions to verify downloads against.

Each element is a pipe-separated string of `version|platform|sha256|length`, where:

    - `version` is the version string
    - `platform` is one of [linux_arm64,linux_x86_64,macos_arm64,macos_x86_64],
    - `sha256` is the 64-character hex representation of the expected sha256
    digest of the download file, as emitted by `shasum -a 256`
    - `length` is the expected length of the download file in bytes, as emitted by
    `wc -c`

E.g., `3.1.2|macos_x86_64|6d0f18cd84b918c7b3edd0203e75569e0c7caecb1367bbbe409b44e28514f5be|42813`.

Values are space-stripped, so pipes can be indented for readability if necessary.

</div>
<br>

<div style="color: purple">
  <h3><code>use_unsupported_version</code></h3>
  <code>--grpc-python-plugin-use-unsupported-version=&lt;UnsupportedVersionUsage&gt;</code><br>
  <code>PANTS_GRPC_PYTHON_PLUGIN_USE_UNSUPPORTED_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">one of: <code>error, warning</code></span><br>
<span style="color: green">default: <code>error</code></span>

<br>


What action to take in case the requested version of grpcpythonplugin is not supported.

Supported grpcpythonplugin versions: unspecified

</div>
<br>

<div style="color: purple">
  <h3><code>url_template</code></h3>
  <code>--grpc-python-plugin-url-template=&lt;str&gt;</code><br>
  <code>PANTS_GRPC_PYTHON_PLUGIN_URL_TEMPLATE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>https://binaries.pantsbuild.org/bin/grpc&lowbar;python&lowbar;plugin/{version}/{platform}/grpc&lowbar;python&lowbar;plugin</code></span>

<br>

URL to download the tool, either as a single binary file or a compressed file (e.g. zip file). You can change this to point to your own hosted file, e.g. to work with proxies or for access via the filesystem through a `file:$abspath` URL (e.g. `file:/this/is/absolute`, possibly by [templating the buildroot in a config file]([Options](doc:options)#config-file-entries)).

Use `{version}` to have the value from --version substituted, and `{platform}` to have a value from --url-platform-mapping substituted in, depending on the current platform. For example, https://github.com/.../protoc-{version}-{platform}.zip.
</div>
<br>

<div style="color: purple">
  <h3><code>url_platform_mapping</code></h3>
  <code>--grpc-python-plugin-url-platform-mapping=&quot;{'key1': val1, 'key2': val2, ...}&quot;</code><br>
  <code>PANTS_GRPC_PYTHON_PLUGIN_URL_PLATFORM_MAPPING</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>{
  "linux&lowbar;arm64": "linux/arm64",
  "linux&lowbar;x86&lowbar;64": "linux/x86&lowbar;64",
  "macos&lowbar;arm64": "macos/x86&lowbar;64",
  "macos&lowbar;x86&lowbar;64": "macos/x86&lowbar;64"
}</pre></span>

<br>

A dictionary mapping platforms to strings to be used when generating the URL to download the tool.

In --url-template, anytime the `{platform}` string is used, Pants will determine the current platform, and substitute `{platform}` with the respective value from your dictionary.

For example, if you define `{"macos_x86_64": "apple-darwin", "linux_x86_64": "unknown-linux"}`, and run Pants on Linux with an intel architecture, then `{platform}` will be substituted in the --url-template option with unknown-linux.
</div>
<br>


## Deprecated options

None