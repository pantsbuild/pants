// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::id::{OptionId, Scope};
use crate::option_id;

#[test]
fn test_option_id_global_switch() {
    let option_id = option_id!(-'x', "bar", "baz");
    assert_eq!(
        OptionId::new(Scope::Global, ["bar", "baz"].iter(), Some('x')).unwrap(),
        option_id
    );
    assert_eq!("GLOBAL", option_id.scope());
}

#[test]
fn test_option_id_global() {
    let option_id = option_id!("bar", "baz");
    assert_eq!(
        OptionId::new(Scope::Global, ["bar", "baz"].iter(), None).unwrap(),
        option_id
    );
    assert_eq!("GLOBAL", option_id.scope());
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
    assert_eq!("foo-bar", option_id.scope());
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
    assert_eq!("foo-bar", option_id.scope());
}
