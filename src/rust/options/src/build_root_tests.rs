// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::fs;
use std::path::PathBuf;

use tempfile::TempDir;

use crate::build_root::BuildRoot;
use std::ops::Deref;

#[test]
fn test_find_cwd() {
    let buildroot = TempDir::new().unwrap();
    let buildroot_path = buildroot.path().to_path_buf();
    let mut sentinel: Option<PathBuf> = None;

    let mut assert_sentinel = |name| {
        if let Some(prior_sentinel) = sentinel.take() {
            fs::remove_file(prior_sentinel).unwrap();
        }
        assert!(BuildRoot::find_from(&buildroot_path).is_err());

        let file = buildroot.path().join(name);
        fs::write(&file, []).unwrap();
        sentinel = Some(file);
        assert_eq!(
            &buildroot_path,
            BuildRoot::find_from(&buildroot_path).unwrap().deref()
        );
    };

    assert_sentinel("BUILDROOT");
    assert_sentinel("BUILD_ROOT");
    assert_sentinel("pants.toml");
}

#[test]
fn test_find_subdir() {
    let buildroot = TempDir::new().unwrap();
    let buildroot_path = buildroot.path().to_path_buf();
    let subdir = buildroot_path.join("foo").join("bar");

    assert!(BuildRoot::find_from(&buildroot_path).is_err());
    assert!(BuildRoot::find_from(&subdir).is_err());

    let sentinel = &buildroot.path().join("pants.toml");
    fs::write(sentinel, []).unwrap();
    assert_eq!(
        &buildroot_path,
        BuildRoot::find_from(&buildroot_path).unwrap().deref()
    );
    assert_eq!(
        &buildroot_path,
        BuildRoot::find_from(&subdir).unwrap().deref()
    );
}
