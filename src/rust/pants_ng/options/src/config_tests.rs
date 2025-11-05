// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashSet;
use std::fs::File;
use std::fs::canonicalize;
use std::fs::create_dir_all;

use options::BuildRoot;
use tempfile::tempdir;

use crate::config::ConfigFinder;
use crate::config::InterpolationMap;

#[test]
fn test_config_discovery() {
    let tmp_dir = tempdir().unwrap();
    let buildroot = BuildRoot::for_path(canonicalize(tmp_dir.path().to_path_buf()).unwrap());
    let dir = buildroot.as_path().join("dir");
    let subdir = dir.join("subdir");
    let subsubdir = subdir.join("subsubdir");

    let root_config = buildroot.as_path().join("pants.toml");
    let root_linux_config = buildroot.as_path().join("pants_linux.toml");
    let dir_config = dir.join("pants.toml");
    let dir_ci_config = dir.join("pants_01.ci.toml");
    let dir_arm64_config = dir.join("pants_02.arm64.toml");
    let subsubdir_config = subsubdir.join("pants.toml");
    let subsubdir_ci_macos_config = subsubdir.join("pants_ci.macos.toml");

    create_dir_all(&subsubdir).unwrap();
    File::create(root_config.as_path()).unwrap();
    File::create(root_linux_config.as_path()).unwrap();
    File::create(dir_config.as_path()).unwrap();
    File::create(dir_ci_config.as_path()).unwrap();
    File::create(dir_arm64_config.as_path()).unwrap();
    File::create(subsubdir_config.as_path()).unwrap();
    File::create(subsubdir_ci_macos_config.as_path()).unwrap();

    let config_finder =
        ConfigFinder::new(Some(buildroot.clone()), InterpolationMap::new()).unwrap();

    let configs = config_finder
        .get_applicable_config_files(&subsubdir, &HashSet::new())
        .unwrap();
    assert_eq!(
        vec![
            root_config.clone(),
            dir_config.clone(),
            subsubdir_config.clone()
        ],
        configs
    );

    let configs = config_finder
        .get_applicable_config_files(
            &subsubdir,
            &HashSet::from(["ci".to_string(), "linux".to_string()]),
        )
        .unwrap();
    assert_eq!(
        vec![
            root_config.clone(),
            root_linux_config.clone(),
            dir_config.clone(),
            dir_ci_config.clone(),
            subsubdir_config.clone()
        ],
        configs
    );

    let configs = config_finder
        .get_applicable_config_files(
            &subsubdir,
            &HashSet::from(["ci".to_string(), "macos".to_string()]),
        )
        .unwrap();
    assert_eq!(
        vec![
            root_config.clone(),
            dir_config.clone(),
            dir_ci_config.clone(),
            subsubdir_config.clone(),
            subsubdir_ci_macos_config.clone()
        ],
        configs
    );

    let configs = config_finder
        .get_applicable_config_files(
            &subsubdir,
            &HashSet::from(["ci".to_string(), "arm64".to_string()]),
        )
        .unwrap();
    assert_eq!(
        vec![
            root_config.clone(),
            dir_config.clone(),
            dir_ci_config.clone(),
            dir_arm64_config.clone(),
            subsubdir_config.clone(),
        ],
        configs
    );
}
