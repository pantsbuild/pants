// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::BTreeSet;
use std::fs::{File, canonicalize, create_dir_all};

use options::BuildRoot;
use options::fromfile::FromfileExpander;
use tempfile::tempdir;

use crate::config::{ConfigFinder, InterpolationMap};

#[test]
fn test_config_discovery() {
    let tmp_dir = tempdir().unwrap();
    let tmp_dir_path = canonicalize(tmp_dir.path()).unwrap();
    let buildroot_dir = tmp_dir_path.join("buildroot");
    let dir = buildroot_dir.join("dir");
    let subdir = dir.join("subdir");
    let subsubdir = subdir.join("subsubdir");

    create_dir_all(&subsubdir).unwrap();

    // This file above the buildroot should never be discovered.
    let file_outside_buildroot = tmp_dir_path.join("pantsng.toml");

    // Configs under the buildroot, each of which may be discovered depending on the context.
    let root_config = buildroot_dir.join("pantsng.toml");
    let root_linux_config = buildroot_dir.as_path().join("pantsng_linux.toml");
    let dir_config = dir.join("pantsng.toml");
    let dir_ci_config = dir.join("pantsng_01.ci.toml");
    let dir_arm64_config = dir.join("pantsng_02.arm64.toml");
    let subsubdir_config = subsubdir.join("pantsng.toml");
    let subsubdir_ci_macos_config = subsubdir.join("pantsng_ci.macos.toml");

    let buildroot = BuildRoot::for_path(canonicalize(buildroot_dir.to_path_buf()).unwrap());

    File::create(file_outside_buildroot.as_path()).unwrap();
    File::create(root_config.as_path()).unwrap();
    File::create(root_linux_config.as_path()).unwrap();
    File::create(dir_config.as_path()).unwrap();
    File::create(dir_ci_config.as_path()).unwrap();
    File::create(dir_arm64_config.as_path()).unwrap();
    File::create(subsubdir_config.as_path()).unwrap();
    File::create(subsubdir_ci_macos_config.as_path()).unwrap();

    let mk_config_finder = |context: BTreeSet<String>| -> ConfigFinder {
        ConfigFinder::new(
            buildroot.clone(),
            FromfileExpander::relative_to(buildroot.clone()),
            InterpolationMap::new(),
            context,
        )
        .unwrap()
    };

    let config_finder = mk_config_finder(BTreeSet::new());
    let configs = config_finder
        .get_applicable_config_files(&subsubdir)
        .unwrap();
    assert_eq!(
        vec![
            root_config.clone(),
            dir_config.clone(),
            subsubdir_config.clone()
        ],
        configs
    );

    let config_finder = mk_config_finder(BTreeSet::from(["ci".to_string(), "linux".to_string()]));
    let configs = config_finder
        .get_applicable_config_files(&subsubdir)
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

    let config_finder = mk_config_finder(BTreeSet::from(["ci".to_string(), "macos".to_string()]));
    let configs = config_finder
        .get_applicable_config_files(&subsubdir)
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

    let config_finder = mk_config_finder(BTreeSet::from(["ci".to_string(), "arm64".to_string()]));
    let configs = config_finder
        .get_applicable_config_files(&subsubdir)
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
