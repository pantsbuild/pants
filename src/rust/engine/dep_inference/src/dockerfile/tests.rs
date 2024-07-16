// Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::collections::HashSet;

use crate::dockerfile::DockerFileInfoCollector;

fn assert_from_tags<const N: usize>(code: &str, imports: [(&str, &str); N]) {
    let mut collector = DockerFileInfoCollector::new(code);
    collector.collect();
    assert_eq!(
        collector.version_tags.into_iter().collect::<HashSet<_>>(),
        HashSet::from_iter(
            imports
                .iter()
                .map(|(s1, s2)| (s1.to_string(), s2.to_string()))
        )
    );
}

fn assert_build_args<const N: usize>(code: &str, build_args: [&str; N]) {
    let mut collector = DockerFileInfoCollector::new(code);
    collector.collect();
    assert_eq!(
        collector.build_args.into_iter().collect::<HashSet<_>>(),
        HashSet::from_iter(build_args.iter().map(|s| s.to_string())),
    );
}

fn assert_copy_from_source_path<const N: usize>(code: &str, files: [&str; N]) {
    let mut collector = DockerFileInfoCollector::new(code);
    collector.collect();
    assert_eq!(
        collector
            .copy_source_paths
            .into_iter()
            .collect::<HashSet<_>>(),
        HashSet::from_iter(files.into_iter().map(str::to_string)),
    );
}

fn assert_copy_build_args<const N: usize>(code: &str, files: [&str; N]) {
    let mut collector = DockerFileInfoCollector::new(code);
    collector.collect();
    assert_eq!(
        collector
            .copy_build_args
            .into_iter()
            .collect::<HashSet<_>>(),
        HashSet::from_iter(files.into_iter().map(str::to_string)),
    );
}

fn assert_from_image_build_args<const N: usize>(code: &str, files: [&str; N]) {
    let mut collector = DockerFileInfoCollector::new(code);
    collector.collect();
    assert_eq!(
        collector
            .from_image_build_args
            .into_iter()
            .collect::<HashSet<_>>(),
        HashSet::from_iter(files.into_iter().map(str::to_string)),
    );
}

#[test]
fn from_instructions() {
    assert_from_tags("FROM python:3.10", [("stage0", "3.10")]);
    assert_from_tags("FROM docker.io/python:3.10", [("stage0", "3.10")]);
    assert_from_tags("FROM ${ARG}", [("stage0", "build-arg:ARG")]);
    assert_from_tags("FROM $ARG", [("stage0", "build-arg:ARG")]);
    assert_from_tags("FROM $ARG AS dynamic", [("dynamic", "build-arg:ARG")]);
    assert_from_tags("FROM python:$VERSION", [("stage0", "$VERSION")]);
    assert_from_tags(
        "FROM digest@sha256:d1f0463b35135852308ea815c2ae54c1734b876d90288ce35828aeeff9899f9d",
        [],
    );
    assert_from_tags(
        "FROM gcr.io/tekton-releases/github.com/tektoncd/operator/cmd/kubernetes/operator:v0.54.0@sha256:d1f0463b35135852308ea815c2ae54c1734b876d90288ce35828aeeff9899f9d",
        [("stage0", "v0.54.0")],
    );
}

#[test]
fn from_instructions_multiple_stages() {
    assert_from_tags(
        r"
FROM untagged
FROM tagged:v1.2
FROM digest@sha256:d1f0463b35135852308ea815c2ae54c1734b876d90288ce35828aeeff9899f9d
FROM gcr.io/tekton-releases/github.com/tektoncd/operator/cmd/kubernetes/operator:v0.54.0@sha256:d1f0463b35135852308ea815c2ae54c1734b876d90288ce35828aeeff9899f9d
FROM $PYTHON_VERSION AS python
FROM python:$VERSION
",
        [
            ("stage0", "latest"),
            ("stage1", "v1.2"),
            // Stage 2 is not pinned with a tag.
            ("stage3", "v0.54.0"),
            ("python", "build-arg:PYTHON_VERSION"), // Parse tag from build arg.
            ("stage5", "$VERSION"),
        ],
    )
}

#[test]
fn arg_instructions() {
    assert_build_args(r#"ARG VAR="value""#, [r#"VAR="value""#]);
    assert_build_args("ARG VAR=value", ["VAR=value"]);
    assert_build_args("ARG VAR", ["VAR"]);
}

#[test]
fn copy_source_file_path_instructions() {
    assert_copy_from_source_path("COPY --from=somewhere my/file to/here", []);
    assert_copy_from_source_path("COPY --from=somewhere my/file b to/here", []);
    assert_copy_from_source_path("COPY my/file to/here", ["my/file"]);
    assert_copy_from_source_path("COPY a b c to/here", ["a", "b", "c"]);
    assert_copy_from_source_path("ARG MY_ARG=value\nCOPY $MY_ARG $ARG", []);
    assert_copy_from_source_path("COPY my/file $ARG", ["my/file"]);
    assert_copy_from_source_path("ARG MY_ARG=value\nCOPY some/dir/$MY_ARG w/e", []);
}

#[test]
fn copy_build_args_instructions() {
    assert_copy_build_args("ARG MY_ARG=value\nCOPY $MY_ARG $ARG", ["MY_ARG=value"]);
    assert_copy_build_args("ARG MY_ARG=\'value\'\nCOPY $MY_ARG $ARG", ["MY_ARG=value"]);
    assert_copy_build_args("ARG MY_ARG=\"value\"\nCOPY $MY_ARG $ARG", ["MY_ARG=value"]);
    assert_copy_build_args("ARG MY_ARG\nCOPY $MY_ARG $ARG", []);
    assert_copy_build_args(
        "ARG MY_ARG=value\nCOPY some/dir/$MY_ARG w/e",
        ["MY_ARG=value"],
    );
}

#[test]
fn from_image_build_args() {
    assert_from_image_build_args(
        r#"
ARG BASE_IMAGE_1=":sibling"
FROM $BASE_IMAGE_1
ARG BASE_IMAGE_2=":sibling@a=42,b=c"
FROM $BASE_IMAGE_2
ARG BASE_IMAGE_3="else/where:weird#name@with=param"
FROM $BASE_IMAGE_3
ARG BASE_IMAGE_4="//src/common:name@parametrized=foo-bar.1"
FROM $BASE_IMAGE_4
ARG BASE_IMAGE_5="should/allow/default-target-name"
FROM $BASE_IMAGE_5
ARG DECOY="this is not a target address"
FROM $DECOY
"#,
        [
            "BASE_IMAGE_1=:sibling",
            "BASE_IMAGE_2=:sibling@a=42,b=c",
            "BASE_IMAGE_3=else/where:weird#name@with=param",
            "BASE_IMAGE_4=//src/common:name@parametrized=foo-bar.1",
            "BASE_IMAGE_5=should/allow/default-target-name",
        ],
    );
}
