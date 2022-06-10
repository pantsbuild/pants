---
title: "helm-unittest"
slug: "reference-helm-unittest"
hidden: false
createdAt: "2022-06-02T21:09:47.609Z"
updatedAt: "2022-06-02T21:09:47.953Z"
---
BDD styled unit test framework for Kubernetes Helm charts as a Helm plugin. (https://github.com/quintush/helm-unittest)

Backend: <span style="color: purple"><code>pants.backend.experimental.helm</code></span>
Config section: <span style="color: purple"><code>[helm-unittest]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>output_type</code></h3>
  <code>--helm-unittest-output-type=&lt;HelmUnitTestReportFormat&gt;</code><br>
  <code>PANTS_HELM_UNITTEST_OUTPUT_TYPE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">one of: <code>XUnit, NUnit, JUnit</code></span><br>
<span style="color: green">default: <code>XUnit</code></span>

<br>

Output type used for the test report
</div>
<br>


## Advanced options

<div style="color: purple">
  <h3><code>version</code></h3>
  <code>--helm-unittest-version=&lt;str&gt;</code><br>
  <code>PANTS_HELM_UNITTEST_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>0.2.8</code></span>

<br>

Use this version of helmunittestsubsystem.
</div>
<br>

<div style="color: purple">
  <h3><code>known_versions</code></h3>
  <code>--helm-unittest-known-versions=&quot;['&lt;str&gt;', '&lt;str&gt;', ...]&quot;</code><br>
  <code>PANTS_HELM_UNITTEST_KNOWN_VERSIONS</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>[
  "0.2.8|linux&lowbar;x86&lowbar;64|d7c452559ad4406a1197435394fbcffe51198060de1aa9b4cb6feaf876776ba0|18299096",
  "0.2.8|linux&lowbar;arm64 |c793e241b063f0540ad9b4acc0a02e5a101bd9daea5bdf4d8562e9b2337fedb2|16943867",
  "0.2.8|macos&lowbar;x86&lowbar;64|1dc95699320894bdebf055c4f4cc084c2cfa0133d3cb7fd6a4c0adca94df5c96|18161928",
  "0.2.8|macos&lowbar;arm64 |436e3167c26f71258b96e32c2877b4f97c051064db941de097cf3db2fc861342|17621648"
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
  <code>--helm-unittest-use-unsupported-version=&lt;UnsupportedVersionUsage&gt;</code><br>
  <code>PANTS_HELM_UNITTEST_USE_UNSUPPORTED_VERSION</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">one of: <code>error, warning</code></span><br>
<span style="color: green">default: <code>error</code></span>

<br>


What action to take in case the requested version of helmunittestsubsystem is not supported.

Supported helmunittestsubsystem versions: unspecified

</div>
<br>

<div style="color: purple">
  <h3><code>url_template</code></h3>
  <code>--helm-unittest-url-template=&lt;str&gt;</code><br>
  <code>PANTS_HELM_UNITTEST_URL_TEMPLATE</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>https://github.com/quintush/helm-unittest/releases/download/v{version}/helm-unittest-{platform}-{version}.tgz</code></span>

<br>

URL to download the tool, either as a single binary file or a compressed file (e.g. zip file). You can change this to point to your own hosted file, e.g. to work with proxies or for access via the filesystem through a `file:$abspath` URL (e.g. `file:/this/is/absolute`, possibly by [templating the buildroot in a config file]([Options](doc:options)#config-file-entries)).

Use `{version}` to have the value from --version substituted, and `{platform}` to have a value from --url-platform-mapping substituted in, depending on the current platform. For example, https://github.com/.../protoc-{version}-{platform}.zip.
</div>
<br>

<div style="color: purple">
  <h3><code>url_platform_mapping</code></h3>
  <code>--helm-unittest-url-platform-mapping=&quot;{'key1': val1, 'key2': val2, ...}&quot;</code><br>
  <code>PANTS_HELM_UNITTEST_URL_PLATFORM_MAPPING</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <pre>{
  "linux&lowbar;arm64": "linux-arm64",
  "linux&lowbar;x86&lowbar;64": "linux-amd64",
  "macos&lowbar;arm64": "macos-arm64",
  "macos&lowbar;x86&lowbar;64": "macos-amd64"
}</pre></span>

<br>

A dictionary mapping platforms to strings to be used when generating the URL to download the tool.

In --url-template, anytime the `{platform}` string is used, Pants will determine the current platform, and substitute `{platform}` with the respective value from your dictionary.

For example, if you define `{"macos_x86_64": "apple-darwin", "linux_x86_64": "unknown-linux"}`, and run Pants on Linux with an intel architecture, then `{platform}` will be substituted in the --url-template option with unknown-linux.
</div>
<br>


## Deprecated options

None