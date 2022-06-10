---
title: "buf"
slug: "reference-buf"
hidden: false
createdAt: "2022-06-02T21:09:35.653Z"
updatedAt: "2022-06-02T21:09:36.083Z"
---
A linter and formatter for Protocol Buffers (https://github.com/bufbuild/buf).

Backend: <span style="color: purple"><code>pants.backend.codegen.protobuf.lint.buf</code></span>
Config section: <span style="color: purple"><code>[buf]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>format_skip</code></h3>
  <code>--[no-]buf-format-skip</code><br>
  <code>PANTS_BUF_FORMAT_SKIP</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Don't use Buf when running `./pants fmt` and `./pants lint`.
</div>
<br>

<div style="color: purple">
  <h3><code>lint_skip</code></h3>
  <code>--[no-]buf-lint-skip</code><br>
  <code>PANTS_BUF_LINT_SKIP</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>False</code></span>

<br>

Don't use Buf when running `./pants lint`.
</div>
<br>

<div style="color: purple">
  <h3><code>format_args</code></h3>
  <code>--buf-format-args=&quot;[&lt;shell_str&gt;, &lt;shell_str&gt;, ...]&quot;</code><br>
  <code>PANTS_BUF_FORMAT_ARGS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Arguments to pass directly to Buf, e.g. `--buf-args='--error-format json'`.
</div>
<br>

<div style="color: purple">
  <h3><code>lint_args</code></h3>
  <code>--buf-lint-args=&quot;[&lt;shell_str&gt;, &lt;shell_str&gt;, ...]&quot;</code><br>
  <code>PANTS_BUF_LINT_ARGS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>[]</code></span>

<br>

Arguments to pass directly to Buf, e.g. `--buf-args='--error-format json'`.
</div>
<br>


## Advanced options

<div style="color: purple">
  <h3><code>version</code></h3>
  <code>--buf-version=&lt;str&gt;</code><br>
  <code>PANTS_BUF_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>v1.3.0</code></span>

<br>

Use this version of Buf.
</div>
<br>

<div style="color: purple">
  <h3><code>known_versions</code></h3>
  <code>--buf-known-versions=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_BUF_KNOWN_VERSIONS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "v1.3.0|linux&lowbar;arm64 |fbfd53c501451b36900247734bfa4cbe86ae05d0f51bc298de8711d5ee374ee5|13940828",
  "v1.3.0|linux&lowbar;x86&lowbar;64|e29c4283b1cd68ada41fa493171c41d7605750d258fcd6ecdf692a63fae95213|15267162",
  "v1.3.0|macos&lowbar;arm64 |147985d7f2816a545792e38b26178ff4027bf16cd3712f6e387a4e3692a16deb|15391890",
  "v1.3.0|macos&lowbar;x86&lowbar;64|3b6bd2e5a5dd758178aee01fb067261baf5d31bfebe93336915bfdf7b21928c4|15955291"
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
  <code>--buf-use-unsupported-version=&lt;UnsupportedVersionUsage&gt;</code><br>
  <code>PANTS_BUF_USE_UNSUPPORTED_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">one of: <code>error, warning</code></span><br>
<span style="color: green">default: <code>error</code></span>

<br>


What action to take in case the requested version of Buf is not supported.

Supported Buf versions: unspecified

</div>
<br>

<div style="color: purple">
  <h3><code>url_template</code></h3>
  <code>--buf-url-template=&lt;str&gt;</code><br>
  <code>PANTS_BUF_URL_TEMPLATE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>https://github.com/bufbuild/buf/releases/download/{version}/buf-{platform}.tar.gz</code></span>

<br>

URL to download the tool, either as a single binary file or a compressed file (e.g. zip file). You can change this to point to your own hosted file, e.g. to work with proxies or for access via the filesystem through a `file:$abspath` URL (e.g. `file:/this/is/absolute`, possibly by [templating the buildroot in a config file]([Options](doc:options)#config-file-entries)).

Use `{version}` to have the value from --version substituted, and `{platform}` to have a value from --url-platform-mapping substituted in, depending on the current platform. For example, https://github.com/.../protoc-{version}-{platform}.zip.
</div>
<br>

<div style="color: purple">
  <h3><code>url_platform_mapping</code></h3>
  <code>--buf-url-platform-mapping=&quot;{'key1': val1, 'key2': val2, ...}&quot;</code><br>
  <code>PANTS_BUF_URL_PLATFORM_MAPPING</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>{
  "linux&lowbar;arm64": "Linux-aarch64",
  "linux&lowbar;x86&lowbar;64": "Linux-x86&lowbar;64",
  "macos&lowbar;arm64": "Darwin-arm64",
  "macos&lowbar;x86&lowbar;64": "Darwin-x86&lowbar;64"
}</pre></span>

<br>

A dictionary mapping platforms to strings to be used when generating the URL to download the tool.

In --url-template, anytime the `{platform}` string is used, Pants will determine the current platform, and substitute `{platform}` with the respective value from your dictionary.

For example, if you define `{"macos_x86_64": "apple-darwin", "linux_x86_64": "unknown-linux"}`, and run Pants on Linux with an intel architecture, then `{platform}` will be substituted in the --url-template option with unknown-linux.
</div>
<br>


## Deprecated options

None