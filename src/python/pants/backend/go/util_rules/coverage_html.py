# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import io
import math
from dataclasses import dataclass
from pathlib import PurePath
from typing import Sequence

import chevron

from pants.backend.go.util_rules.coverage import GoCoverMode
from pants.backend.go.util_rules.coverage_profile import (
    GoCoverageBoundary,
    GoCoverageProfile,
    parse_go_coverage_profiles,
)
from pants.engine.fs import DigestContents
from pants.engine.internals.native_engine import Digest
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule

# Adapted from Go toolchain.
# See https://github.com/golang/go/blob/a0441c7ae3dea57a0553c9ea77e184c34b7da40f/src/cmd/cover/html.go
#
# Note: `go tool cover` could not be used for the HTML support because it attempts to find the source files
# on its own using go list.
# See https://github.com/golang/go/blob/a0441c7ae3dea57a0553c9ea77e184c34b7da40f/src/cmd/cover/func.go#L200-L222.
#
# The Go rules have been engineered to avoid `go list` due to it needing, among other things, all transitive
# third-party dependencies available to it when analyzing first-party sources. Thus, the use of `go list` by
# `go tool cover` in this case means we cannot use `go tool cover` to generate the HTML.
#
# Original copyright:
#  // Copyright 2013 The Go Authors. All rights reserved.
#  // Use of this source code is governed by a BSD-style
#  // license that can be found in the LICENSE file.


@dataclass(frozen=True)
class RenderGoCoverageProfileToHtmlRequest:
    raw_coverage_profile: bytes
    description_of_origin: str
    sources_digest: Digest
    sources_dir_path: str


@dataclass(frozen=True)
class RenderGoCoverageProfileToHtmlResult:
    html_output: bytes


@dataclass(frozen=True)
class RenderedFile:
    name: str
    body: str
    coverage: float


def _get_pkg_name(filename: str) -> str | None:
    elems = filename.split("/")
    i = len(elems) - 2
    while i >= 0:
        if elems[i] != "":
            return elems[i]
        i -= 1
    return None


def _percent_covered(profile: GoCoverageProfile) -> float:
    covered = 0
    total = 0
    for block in profile.blocks:
        total += block.num_stmt
        if block.count > 0:
            covered += block.num_stmt
    if total == 0:
        return 0.0
    return float(covered) / float(total) * 100.0


def _render_source_file(content: bytes, boundaries: Sequence[GoCoverageBoundary]) -> str:
    rendered = io.StringIO()
    for i in range(len(content)):
        while boundaries and boundaries[0].offset == i:
            b = boundaries[0]
            if b.start:
                n = 0
                if b.count > 0:
                    n = int(math.floor(b.norm * 9)) + 1
                rendered.write(f'<span class="cov{n}" title="{b.count}">')
            else:
                rendered.write("</span>")
            boundaries = boundaries[1:]
        c = content[i]
        if c == ord(">"):
            rendered.write("&gt;")
        elif c == ord("<"):
            rendered.write("&lt;")
        elif c == ord("&"):
            rendered.write("&amp;")
        elif c == ord("\t"):
            rendered.write("        ")
        else:
            rendered.write(chr(c))
    return rendered.getvalue()


@rule
async def render_go_coverage_profile_to_html(
    request: RenderGoCoverageProfileToHtmlRequest,
) -> RenderGoCoverageProfileToHtmlResult:
    digest_contents = await Get(DigestContents, Digest, request.sources_digest)
    profiles = parse_go_coverage_profiles(
        request.raw_coverage_profile, description_of_origin=request.description_of_origin
    )

    files: list[RenderedFile] = []
    pkg_name: str | None = None
    cover_mode_set = False
    for profile in profiles:
        if pkg_name is None:
            pkg_name = _get_pkg_name(profile.filename)
        if profile.cover_mode == GoCoverMode.SET:
            cover_mode_set = True

        name = PurePath(profile.filename).name

        file_contents: bytes | None = None
        full_file_path = str(PurePath(request.sources_dir_path, name))
        for entry in digest_contents:
            if entry.path == full_file_path:
                file_contents = entry.content
                break

        if file_contents is None:
            continue

        files.append(
            RenderedFile(
                name=name,
                body=_render_source_file(file_contents, profile.boundaries(file_contents)),
                coverage=_percent_covered(profile),
            )
        )

    rendered = chevron.render(
        template=_HTML_TEMPLATE,
        data={
            "pkg_name": pkg_name or "",
            "set": cover_mode_set,
            "files": [
                {
                    "i": i,
                    "name": file.name,
                    "coverage": f"{file.coverage:.1f}",
                    "body": file.body,
                }
                for i, file in enumerate(files)
            ],
        },
    )

    return RenderGoCoverageProfileToHtmlResult(rendered.encode())


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
    <head>
        <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
        <title>{{#pkg_name}}{{pkg_name}}: {{/pkg_name}}Go Coverage Report</title>
        <style>
            body {
                background: black;
                color: rgb(80, 80, 80);
            }
            body, pre, #legend span {
                font-family: Menlo, monospace;
                font-weight: bold;
            }
            #topbar {
                background: black;
                position: fixed;
                top: 0; left: 0; right: 0;
                height: 42px;
                border-bottom: 1px solid rgb(80, 80, 80);
            }
            #content {
                margin-top: 50px;
            }
            #nav, #legend {
                float: left;
                margin-left: 10px;
            }
            #legend {
                margin-top: 12px;
            }
            #nav {
                margin-top: 10px;
            }
            #legend span {
                margin: 0 5px;
            }
            <!--
            Colors generated by:
            def rgb(n):
                if n == 0:
                    return "rgb(192, 0, 0)" # Red
                # Gradient from gray to green.
                r = 128 - 12*(n-1)
                g = 128 + 12*(n-1)
                b = 128 + 3*(n-1)
                return f"rgb({r}, {g}, {b})"

            def colors():
                for i in range(11):
                    print(f".cov{i} {{ color: {rgb(i)} }}")
            -->
            .cov0 { color: rgb(192, 0, 0) }
            .cov1 { color: rgb(128, 128, 128) }
            .cov2 { color: rgb(116, 140, 131) }
            .cov3 { color: rgb(104, 152, 134) }
            .cov4 { color: rgb(92, 164, 137) }
            .cov5 { color: rgb(80, 176, 140) }
            .cov6 { color: rgb(68, 188, 143) }
            .cov7 { color: rgb(56, 200, 146) }
            .cov8 { color: rgb(44, 212, 149) }
            .cov9 { color: rgb(32, 224, 152) }
            .cov10 { color: rgb(20, 236, 155) }
        </style>
    </head>
    <body>
        <div id="topbar">
            <div id="nav">
                <select id="files">
                    {{#files}}
                    <option value="file{{i}}">{{name}} ({{coverage}}%)</option>
                    {{/files}}
                </select>
            </div>
            <div id="legend">
                <span>not tracked</span>
                {{#set}}
                <span class="cov0">not covered</span>
                <span class="cov8">covered</span>
                {{/set}}
                {{^set}}
                <span class="cov0">no coverage</span>
                <span class="cov1">low coverage</span>
                <span class="cov2">*</span>
                <span class="cov3">*</span>
                <span class="cov4">*</span>
                <span class="cov5">*</span>
                <span class="cov6">*</span>
                <span class="cov7">*</span>
                <span class="cov8">*</span>
                <span class="cov9">*</span>
                <span class="cov10">high coverage</span>
                {{/set}}
            </div>
        </div>
        <div id="content">
            {{#files}}
            <pre class="file" id="file{{i}}" style="display: none">{{{body}}}</pre>
            {{/files}}
        </div>
    </body>
    <script>
        (function() {
            var files = document.getElementById('files');
            var visible;
            files.addEventListener('change', onChange, false);
            function select(part) {
                if (visible)
                    visible.style.display = 'none';
                visible = document.getElementById(part);
                if (!visible)
                    return;
                files.value = part;
                visible.style.display = 'block';
                location.hash = part;
            }
            function onChange() {
                select(files.value);
                window.scrollTo(0, 0);
            }
            if (location.hash != "") {
                select(location.hash.substr(1));
            }
            if (!visible) {
                select("file0");
            }
        })();
    </script>
</html>
"""


def rules():
    return collect_rules()
