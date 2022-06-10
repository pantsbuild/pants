---
title: "regex-lint"
slug: "reference-regex-lint"
hidden: false
createdAt: "2022-06-02T21:10:06.686Z"
updatedAt: "2022-06-02T21:10:07.273Z"
---
Lint your code using regex patterns, e.g. to check for copyright headers.

To activate this with the `lint` goal, you must set `[regex-lint].config`.

Unlike other linters, this can run on files not owned by targets, such as BUILD files. To run on those, use `lint '**'` rather than `lint ::`, for example. Unfortunately, `--changed-since=<sha>` does not yet cause this linter to run. We are exploring how to improve both these gotchas.

Backend: <span style="color: purple"><code>pants.backend.project_info</code></span>
Config section: <span style="color: purple"><code>[regex-lint]</code></span>

## Basic options

<div style="color: purple">
  <h3><code>config</code></h3>
  <code>--regex-lint-config=&quot;{'key1': val1, 'key2': val2, ...}&quot;</code><br>
  <code>PANTS_REGEX_LINT_CONFIG</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">default: <code>{}</code></span>

<br>

Config schema is as follows:

    ```
    {
    'required_matches': {
        'path_pattern1': [content_pattern1, content_pattern2],
        'path_pattern2': [content_pattern1, content_pattern3],
        ...
    },
    'path_patterns': [
        {
        'name': path_pattern1',
        'pattern': <path regex pattern>,
        'inverted': True|False (defaults to False),
        'content_encoding': <encoding> (defaults to utf8)
        },
        ...
    ],
    'content_patterns': [
        {
        'name': 'content_pattern1',
        'pattern': <content regex pattern>,
        'inverted': True|False (defaults to False)
        }
        ...
    ]
    }
    ```

Meaning: if a file matches some path pattern, its content must match all the corresponding content patterns.

It's often helpful to load this config from a JSON or YAML file. To do that, set `[regex-lint].config = '@path/to/config.yaml'`, for example.
</div>
<br>

<div style="color: purple">
  <h3><code>detail_level</code></h3>
  <code>--regex-lint-detail-level=&lt;DetailLevel&gt;</code><br>
  <code>PANTS_REGEX_LINT_DETAIL_LEVEL</code><br>
</div>
<div style="padding-left: 2em;">
<span style="color: green">one of: <code>none, summary, nonmatching, names, all</code></span><br>
<span style="color: green">default: <code>nonmatching</code></span>

<br>

How much detail to include in the result.
</div>
<br>


## Advanced options

None

## Deprecated options

None