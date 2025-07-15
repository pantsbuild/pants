// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use options::render_choice;

#[test]
fn test() {
    assert!(render_choice(&[]).is_none());
    assert_eq!("One".to_owned(), render_choice(&["One"]).unwrap());
    assert_eq!(
        "One or Two".to_owned(),
        render_choice(&["One", "Two"]).unwrap()
    );
    assert_eq!(
        "One, Two or Three".to_owned(),
        render_choice(&["One", "Two", "Three"]).unwrap()
    );
}
