// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use crate::externs::interface::generate_panic_string;

use std::any::Any;

#[test]
fn test_panic_string() {
    let a: &str = "a str panic payload";
    assert_eq!(
        generate_panic_string(&a as &(dyn Any + Send)),
        "panic at 'a str panic payload'"
    );

    let b: String = "a String panic payload".to_string();
    assert_eq!(
        generate_panic_string(&b as &(dyn Any + Send)),
        "panic at 'a String panic payload'"
    );

    let c: u32 = 18;
    let output = generate_panic_string(&c as &(dyn Any + Send));
    assert!(output.contains("Non-string panic payload at"));
}
