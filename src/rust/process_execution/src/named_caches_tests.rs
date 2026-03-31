// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use crate::named_caches::CacheName;

#[test]
fn alphanumeric_lowercase_are_valid() {
    let name = "__mynamed_cache_1";
    let cache_name = CacheName::new(name.to_string());
    assert!(cache_name.is_ok());
    assert_eq!(name, cache_name.unwrap().name());
}

#[test]
fn uppercase_characters_are_invalid() {
    let name = "mYnamedcache";
    let cache_name = CacheName::new(name.to_string());
    assert!(cache_name.is_err());
}
