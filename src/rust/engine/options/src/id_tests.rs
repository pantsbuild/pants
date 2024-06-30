// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::id::{is_valid_scope_name, OptionId, Scope};
use crate::option_id;

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

#[test]
fn test_option_id_global_switch() {
    let option_id = option_id!(-'x', "bar", "baz");
    assert_eq!(
        OptionId::new(Scope::Global, ["bar", "baz"].iter(), Some('x')).unwrap(),
        option_id
    );
    assert_eq!("GLOBAL", option_id.scope.name());
}

#[test]
fn test_option_id_global() {
    let option_id = option_id!("bar", "baz");
    assert_eq!(
        OptionId::new(Scope::Global, ["bar", "baz"].iter(), None).unwrap(),
        option_id
    );
    assert_eq!("GLOBAL", option_id.scope.name());
}

#[test]
fn test_option_id_scope_switch() {
    let option_id = option_id!(-'f', ["foo-bar"], "baz", "spam");
    assert_eq!(
        OptionId::new(
            Scope::Scope("foo-bar".to_owned()),
            ["baz", "spam"].iter(),
            Some('f')
        )
        .unwrap(),
        option_id
    );
    assert_eq!("foo-bar", option_id.scope.name());
}

#[test]
fn test_option_id_scope() {
    let option_id = option_id!(["foo-bar"], "baz", "spam");
    assert_eq!(
        OptionId::new(
            Scope::Scope("foo-bar".to_owned()),
            ["baz", "spam"].iter(),
            None
        )
        .unwrap(),
        option_id
    );
    assert_eq!("foo-bar", option_id.scope.name());
}
