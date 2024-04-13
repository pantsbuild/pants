// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use crate::RelativePath;

#[test]
fn relative_path_ok() {
    assert_eq!(Some("a"), RelativePath::new("a").unwrap().to_str());
    assert_eq!(Some("a"), RelativePath::new("./a").unwrap().to_str());
    assert_eq!(Some("a"), RelativePath::new("b/../a").unwrap().to_str());
    assert_eq!(
        Some("a/c"),
        RelativePath::new("b/../a/././c").unwrap().to_str()
    );
}

#[test]
fn relative_path_err() {
    assert!(RelativePath::new("../a").is_err());
    assert!(RelativePath::new("/a").is_err());
}

#[test]
fn relative_path_normalize() {
    assert_eq!(Some("a"), RelativePath::new("a/").unwrap().to_str());
}
