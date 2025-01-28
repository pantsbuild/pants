// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::scope::is_valid_scope_name;

#[test]
fn test_is_valid_scope_name() {
    assert!(is_valid_scope_name("test"));
    assert!(is_valid_scope_name("test1"));
    assert!(is_valid_scope_name("generate-lockfiles"));
    assert!(is_valid_scope_name("i_dont_like_underscores"));

    assert!(!is_valid_scope_name("pants"));
    assert!(!is_valid_scope_name("No-Caps"));
    assert!(!is_valid_scope_name("looks/like/a/target"));
    assert!(!is_valid_scope_name("//:target"));
    assert!(!is_valid_scope_name("-b"));
    assert!(!is_valid_scope_name("--flag=value"));
}
