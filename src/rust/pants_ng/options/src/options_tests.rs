// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::BTreeMap;
use std::fs::{File, canonicalize, create_dir_all};
use std::io::Write;
use std::path::PathBuf;

use options::{BuildRoot, Env, OptionId, Scope};
use tempfile::tempdir;

use crate::options::{Options, SourcePartition};
use crate::pants_invocation::PantsInvocation;

fn mk_options(buildroot: BuildRoot, context: Option<Vec<String>>) -> Options {
    Options::new(
        &PantsInvocation::empty(),
        Env {
            env: BTreeMap::new(),
        },
        Some(buildroot),
        context,
        false,
    )
    .unwrap()
}

fn test_option_id() -> OptionId {
    OptionId::new(Scope::Global, ["test", "option"].iter(), None).unwrap()
}

fn write_config(path: &PathBuf, value: &str) {
    let mut file = File::create(path).unwrap();
    writeln!(file, "[GLOBAL]").unwrap();
    writeln!(file, "test_option = \"{}\"", value).unwrap();
}

struct ExpectedPartition {
    paths: Vec<PathBuf>,
    expected_value: Option<String>,
}

fn paths_and_values(partitions: Vec<SourcePartition>) -> Vec<(Vec<PathBuf>, Option<String>)> {
    let option_id = test_option_id();
    partitions
        .into_iter()
        .map(|p| {
            let value = p
                .options_reader
                .parse_string_optional(&option_id, Some("defaultval"))
                .unwrap()
                .value;
            (p.paths, value)
        })
        .collect()
}

fn assert_partitions(partitions: Vec<SourcePartition>, expected: Vec<ExpectedPartition>) {
    let actual = paths_and_values(partitions);
    let mut expected_sorted: Vec<(Vec<PathBuf>, Option<String>)> = expected
        .into_iter()
        .map(|e| (e.paths, e.expected_value))
        .collect();
    expected_sorted.sort_by(|a, b| a.0.cmp(&b.0));
    assert_eq!(actual, expected_sorted);
}

#[test]
fn test_partition_sources_empty() {
    let tmp_dir = tempdir().unwrap();
    let tmp_dir_path = canonicalize(tmp_dir.path()).unwrap();
    let buildroot_dir = tmp_dir_path.join("buildroot");
    create_dir_all(&buildroot_dir).unwrap();

    let buildroot = BuildRoot::for_path(buildroot_dir);
    let options = mk_options(buildroot, None);

    let partitions = options.partition_sources(vec![]).unwrap();
    assert!(partitions.is_empty());
}

#[test]
fn test_partition_sources_single_file_no_config() {
    let tmp_dir = tempdir().unwrap();
    let tmp_dir_path = canonicalize(tmp_dir.path()).unwrap();
    let buildroot_dir = tmp_dir_path.join("buildroot");
    let dir = buildroot_dir.join("dir");
    create_dir_all(&dir).unwrap();

    let file1 = dir.join("file1.txt");
    File::create(&file1).unwrap();

    let buildroot = BuildRoot::for_path(buildroot_dir);
    let options = mk_options(buildroot, None);

    let partitions = options.partition_sources(vec![file1.clone()]).unwrap();
    assert_partitions(
        partitions,
        vec![ExpectedPartition {
            paths: vec![file1],
            expected_value: Some("defaultval".to_string()),
        }],
    );
}

#[test]
fn test_partition_sources_single_file_with_config() {
    let tmp_dir = tempdir().unwrap();
    let tmp_dir_path = canonicalize(tmp_dir.path()).unwrap();
    let buildroot_dir = tmp_dir_path.join("buildroot");
    let dir = buildroot_dir.join("dir");
    create_dir_all(&dir).unwrap();

    let file1 = dir.join("file1.txt");
    File::create(&file1).unwrap();

    let config = dir.join("pantsng.toml");
    write_config(&config, "value_from_dir");

    let buildroot = BuildRoot::for_path(buildroot_dir);
    let options = mk_options(buildroot, None);

    let partitions = options.partition_sources(vec![file1.clone()]).unwrap();
    assert_partitions(
        partitions,
        vec![ExpectedPartition {
            paths: vec![file1],
            expected_value: Some("value_from_dir".to_string()),
        }],
    );
}

#[test]
fn test_partition_sources_multiple_files_same_dir() {
    let tmp_dir = tempdir().unwrap();
    let tmp_dir_path = canonicalize(tmp_dir.path()).unwrap();
    let buildroot_dir = tmp_dir_path.join("buildroot");
    let dir = buildroot_dir.join("dir");
    create_dir_all(&dir).unwrap();

    let file1 = dir.join("file1.txt");
    let file2 = dir.join("file2.txt");
    File::create(&file1).unwrap();
    File::create(&file2).unwrap();

    let config = dir.join("pantsng.toml");
    write_config(&config, "shared_value");

    let buildroot = BuildRoot::for_path(buildroot_dir);
    let options = mk_options(buildroot, None);

    let partitions = options
        .partition_sources(vec![file1.clone(), file2.clone()])
        .unwrap();

    assert_partitions(
        partitions,
        vec![ExpectedPartition {
            paths: vec![file1, file2],
            expected_value: Some("shared_value".to_string()),
        }],
    );
}

#[test]
fn test_partition_sources_files_in_different_dirs_no_configs() {
    let tmp_dir = tempdir().unwrap();
    let tmp_dir_path = canonicalize(tmp_dir.path()).unwrap();
    let buildroot_dir = tmp_dir_path.join("buildroot");
    let dir1 = buildroot_dir.join("dir1");
    let dir2 = buildroot_dir.join("dir2");
    create_dir_all(&dir1).unwrap();
    create_dir_all(&dir2).unwrap();

    let file1 = dir1.join("file1.txt");
    let file2 = dir2.join("file2.txt");
    File::create(&file1).unwrap();
    File::create(&file2).unwrap();

    let buildroot = BuildRoot::for_path(buildroot_dir);
    let options = mk_options(buildroot, None);

    let partitions = options
        .partition_sources(vec![file1.clone(), file2.clone()])
        .unwrap();

    assert_partitions(
        partitions,
        vec![ExpectedPartition {
            paths: vec![file1, file2],
            expected_value: Some("defaultval".to_string()),
        }],
    );
}

#[test]
fn test_partition_sources_files_in_different_dirs_different_configs() {
    let tmp_dir = tempdir().unwrap();
    let tmp_dir_path = canonicalize(tmp_dir.path()).unwrap();
    let buildroot_dir = tmp_dir_path.join("buildroot");
    let dir1 = buildroot_dir.join("dir1");
    let dir2 = buildroot_dir.join("dir2");
    create_dir_all(&dir1).unwrap();
    create_dir_all(&dir2).unwrap();

    let file1 = dir1.join("file1.txt");
    let file2 = dir2.join("file2.txt");
    File::create(&file1).unwrap();
    File::create(&file2).unwrap();

    let config1 = dir1.join("pantsng.toml");
    write_config(&config1, "value_from_dir1");
    let config2 = dir2.join("pantsng.toml");
    write_config(&config2, "value_from_dir2");

    let buildroot = BuildRoot::for_path(buildroot_dir);
    let options = mk_options(buildroot, None);

    let partitions = options
        .partition_sources(vec![file1.clone(), file2.clone()])
        .unwrap();

    // Each directory has a different config, so they should be in different partitions.
    assert_partitions(
        partitions,
        vec![
            ExpectedPartition {
                paths: vec![file1],
                expected_value: Some("value_from_dir1".to_string()),
            },
            ExpectedPartition {
                paths: vec![file2],
                expected_value: Some("value_from_dir2".to_string()),
            },
        ],
    );
}

#[test]
fn test_partition_sources_one_dir_with_config_one_without() {
    let tmp_dir = tempdir().unwrap();
    let tmp_dir_path = canonicalize(tmp_dir.path()).unwrap();
    let buildroot_dir = tmp_dir_path.join("buildroot");
    let dir1 = buildroot_dir.join("dir1");
    let dir2 = buildroot_dir.join("dir2");
    create_dir_all(&dir1).unwrap();
    create_dir_all(&dir2).unwrap();

    let file1 = dir1.join("file1.txt");
    let file2 = dir2.join("file2.txt");
    File::create(&file1).unwrap();
    File::create(&file2).unwrap();

    // Only dir1 has a config.
    let config1 = dir1.join("pantsng.toml");
    write_config(&config1, "value_from_dir1");

    let buildroot = BuildRoot::for_path(buildroot_dir);
    let options = mk_options(buildroot, None);

    let partitions = options
        .partition_sources(vec![file1.clone(), file2.clone()])
        .unwrap();

    // dir1 has a config, dir2 doesn't, so they should be in different partitions.
    assert_partitions(
        partitions,
        vec![
            ExpectedPartition {
                paths: vec![file1],
                expected_value: Some("value_from_dir1".to_string()),
            },
            ExpectedPartition {
                paths: vec![file2],
                expected_value: Some("defaultval".to_string()),
            },
        ],
    );
}

#[test]
fn test_partition_sources_with_contextual_configs() {
    let tmp_dir = tempdir().unwrap();
    let tmp_dir_path = canonicalize(tmp_dir.path()).unwrap();
    let buildroot_dir = tmp_dir_path.join("buildroot");
    let dir1 = buildroot_dir.join("dir1");
    let dir2 = buildroot_dir.join("dir2");
    create_dir_all(&dir1).unwrap();
    create_dir_all(&dir2).unwrap();

    let file1 = dir1.join("file1.txt");
    let file2 = dir2.join("file2.txt");
    File::create(&file1).unwrap();
    File::create(&file2).unwrap();

    // Create a context-specific config file in dir1 that only applies to "ci" context.
    let ci_config = dir1.join("pantsng_ci.toml");
    write_config(&ci_config, "ci_value");

    let buildroot = BuildRoot::for_path(buildroot_dir.clone());

    // Without "ci" in context, both dirs have no applicable configs.
    let options = mk_options(buildroot.clone(), Some(vec![]));
    let partitions = options
        .partition_sources(vec![file1.clone(), file2.clone()])
        .unwrap();
    assert_partitions(
        partitions,
        vec![ExpectedPartition {
            paths: vec![file1.clone(), file2.clone()],
            expected_value: Some("defaultval".to_string()),
        }],
    );

    // With "ci" in context, dir1 has an applicable config but dir2 doesn't.
    let options = mk_options(buildroot, Some(vec!["ci".to_string()]));
    let partitions = options
        .partition_sources(vec![file1.clone(), file2.clone()])
        .unwrap();
    assert_partitions(
        partitions,
        vec![
            ExpectedPartition {
                paths: vec![file1],
                expected_value: Some("ci_value".to_string()),
            },
            ExpectedPartition {
                paths: vec![file2],
                expected_value: Some("defaultval".to_string()),
            },
        ],
    );
}

#[test]
fn test_partition_sources_dedupes_paths() {
    let tmp_dir = tempdir().unwrap();
    let tmp_dir_path = canonicalize(tmp_dir.path()).unwrap();
    let buildroot_dir = tmp_dir_path.join("buildroot");
    let dir = buildroot_dir.join("dir");
    create_dir_all(&dir).unwrap();

    let file1 = dir.join("file1.txt");
    File::create(&file1).unwrap();

    let config = dir.join("pantsng.toml");
    write_config(&config, "dedup_value");

    let buildroot = BuildRoot::for_path(buildroot_dir);
    let options = mk_options(buildroot, None);

    // Pass the same file multiple times.
    let partitions = options
        .partition_sources(vec![file1.clone(), file1.clone(), file1.clone()])
        .unwrap();

    // After dedup, should only have one path.
    assert_partitions(
        partitions,
        vec![ExpectedPartition {
            paths: vec![file1],
            expected_value: Some("dedup_value".to_string()),
        }],
    );
}

#[test]
fn test_partition_sources_handles_directories() {
    let tmp_dir = tempdir().unwrap();
    let tmp_dir_path = canonicalize(tmp_dir.path()).unwrap();
    let buildroot_dir = tmp_dir_path.join("buildroot");
    let dir1 = buildroot_dir.join("dir1");
    let dir2 = buildroot_dir.join("dir2");
    create_dir_all(&dir1).unwrap();
    create_dir_all(&dir2).unwrap();

    // Create a config file in dir1.
    let config1 = dir1.join("pantsng.toml");
    write_config(&config1, "dir1_value");

    let buildroot = BuildRoot::for_path(buildroot_dir);
    let options = mk_options(buildroot, None);

    // Pass directories as paths.
    let partitions = options
        .partition_sources(vec![dir1.clone(), dir2.clone()])
        .unwrap();

    // dir1 has config, dir2 doesn't, so they should be in different partitions.
    assert_partitions(
        partitions,
        vec![
            ExpectedPartition {
                paths: vec![dir1],
                expected_value: Some("dir1_value".to_string()),
            },
            ExpectedPartition {
                paths: vec![dir2],
                expected_value: Some("defaultval".to_string()),
            },
        ],
    );
}

#[test]
fn test_partition_sources_mixed_files_and_dirs() {
    let tmp_dir = tempdir().unwrap();
    let tmp_dir_path = canonicalize(tmp_dir.path()).unwrap();
    let buildroot_dir = tmp_dir_path.join("buildroot");
    let dir = buildroot_dir.join("dir");
    create_dir_all(&dir).unwrap();

    let file1 = dir.join("file1.txt");
    File::create(&file1).unwrap();

    let config = dir.join("pantsng.toml");
    write_config(&config, "mixed_value");

    let buildroot = BuildRoot::for_path(buildroot_dir);
    let options = mk_options(buildroot, None);

    // Pass both a file and its parent directory.
    let partitions = options
        .partition_sources(vec![file1.clone(), dir.clone()])
        .unwrap();

    // Both use the same directory for config lookup, so same partition.
    assert_partitions(
        partitions,
        vec![ExpectedPartition {
            paths: vec![dir, file1],
            expected_value: Some("mixed_value".to_string()),
        }],
    );
}

#[test]
fn test_partition_sources_nested_directories() {
    let tmp_dir = tempdir().unwrap();
    let tmp_dir_path = canonicalize(tmp_dir.path()).unwrap();
    let buildroot_dir = tmp_dir_path.join("buildroot");
    let dir = buildroot_dir.join("dir");
    let subdir = dir.join("subdir");
    create_dir_all(&subdir).unwrap();

    let file1 = dir.join("file1.txt");
    let file2 = subdir.join("file2.txt");
    File::create(&file1).unwrap();
    File::create(&file2).unwrap();

    // Create a config in the subdir only.
    let subdir_config = subdir.join("pantsng.toml");
    write_config(&subdir_config, "subdir_value");

    let buildroot = BuildRoot::for_path(buildroot_dir);
    let options = mk_options(buildroot, None);

    let partitions = options
        .partition_sources(vec![file1.clone(), file2.clone()])
        .unwrap();

    // file1 in dir has no configs, file2 in subdir has one config.
    assert_partitions(
        partitions,
        vec![
            ExpectedPartition {
                paths: vec![file1],
                expected_value: Some("defaultval".to_string()),
            },
            ExpectedPartition {
                paths: vec![file2],
                expected_value: Some("subdir_value".to_string()),
            },
        ],
    );
}

#[test]
fn test_partition_sources_inherits_parent_configs() {
    let tmp_dir = tempdir().unwrap();
    let tmp_dir_path = canonicalize(tmp_dir.path()).unwrap();
    let buildroot_dir = tmp_dir_path.join("buildroot");
    let dir = buildroot_dir.join("dir");
    let subdir = dir.join("subdir");
    create_dir_all(&subdir).unwrap();

    let file1 = dir.join("file1.txt");
    let file2 = subdir.join("file2.txt");
    File::create(&file1).unwrap();
    File::create(&file2).unwrap();

    // Create a config in the parent dir (not subdir).
    let dir_config = dir.join("pantsng.toml");
    write_config(&dir_config, "parent_value");

    let buildroot = BuildRoot::for_path(buildroot_dir);
    let options = mk_options(buildroot, None);

    let partitions = options
        .partition_sources(vec![file1.clone(), file2.clone()])
        .unwrap();

    // Both files inherit the config from dir, so they should be in the same partition.
    assert_partitions(
        partitions,
        vec![ExpectedPartition {
            paths: vec![file1, file2],
            expected_value: Some("parent_value".to_string()),
        }],
    );
}

#[test]
fn test_partition_sources_child_overrides_parent_config() {
    let tmp_dir = tempdir().unwrap();
    let tmp_dir_path = canonicalize(tmp_dir.path()).unwrap();
    let buildroot_dir = tmp_dir_path.join("buildroot");
    let dir = buildroot_dir.join("dir");
    let subdir = dir.join("subdir");
    create_dir_all(&subdir).unwrap();

    let file1 = dir.join("file1.txt");
    let file2 = subdir.join("file2.txt");
    File::create(&file1).unwrap();
    File::create(&file2).unwrap();

    // Create configs in both parent and child dirs.
    let dir_config = dir.join("pantsng.toml");
    write_config(&dir_config, "parent_value");
    let subdir_config = subdir.join("pantsng.toml");
    write_config(&subdir_config, "child_value");

    let buildroot = BuildRoot::for_path(buildroot_dir);
    let options = mk_options(buildroot, None);

    let partitions = options
        .partition_sources(vec![file1.clone(), file2.clone()])
        .unwrap();

    // file1 gets parent config, file2 gets child config (which overrides parent).
    assert_partitions(
        partitions,
        vec![
            ExpectedPartition {
                paths: vec![file1],
                expected_value: Some("parent_value".to_string()),
            },
            ExpectedPartition {
                paths: vec![file2],
                // Child config takes precedence.
                expected_value: Some("child_value".to_string()),
            },
        ],
    );
}
