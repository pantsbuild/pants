// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::args::Args;
use crate::option_id;
use crate::{ListEdit, ListEditAction, OptionId, OptionsSource};

fn args<I: IntoIterator<Item = &'static str>>(args: I) -> Args {
    Args {
        args: args.into_iter().map(str::to_owned).collect(),
    }
}

#[test]
fn test_display() {
    let args = args([]);
    assert_eq!("--global".to_owned(), args.display(&option_id!("global")));
    assert_eq!(
        "--scope-name".to_owned(),
        args.display(&option_id!("scope", "name"))
    );
    assert_eq!(
        "--scope-full-name".to_owned(),
        args.display(&option_id!(-'f', "scope", "full", "name"))
    );
}

#[test]
fn test_string() {
    let args = args([
        "-u=swallow",
        "--foo=bar",
        "--baz-spam=eggs",
        "--baz-spam=cheese",
    ]);

    let assert_string = |expected: &str, id: OptionId| {
        assert_eq!(expected.to_owned(), args.get_string(&id).unwrap().unwrap())
    };

    assert_string("bar", option_id!("foo"));
    assert_string("cheese", option_id!("baz", "spam"));
    assert_string("swallow", option_id!(-'u', "unladen", "capacity"));

    assert!(args.get_string(&option_id!("dne")).unwrap().is_none());
}

#[test]
fn test_bool() {
    let args = args([
        "-c=swallow",
        "--foo=false",
        "-f",
        "--no-bar",
        "--baz=true",
        "--baz=FALSE",
        "--no-spam-eggs=False",
        "--no-b=True",
    ]);

    let assert_bool =
        |expected: bool, id: OptionId| assert_eq!(expected, args.get_bool(&id).unwrap().unwrap());

    assert_bool(true, option_id!(-'f', "foo"));
    assert_bool(false, option_id!("bar"));
    assert_bool(false, option_id!(-'b', "baz"));
    assert_bool(true, option_id!("spam", "eggs"));

    assert!(args.get_bool(&option_id!("dne")).unwrap().is_none());
    assert_eq!(
        "Got 'swallow' for -c. Expected 'true' or 'false'.".to_owned(),
        args.get_bool(&option_id!(-'c', "unladen", "capacity"))
            .unwrap_err()
    );
}

#[test]
fn test_float() {
    let args = args([
        "-j=4",
        "--foo=42",
        "--foo=3.14",
        "--baz-spam=1.137",
        "--bad=swallow",
    ]);

    let assert_float =
        |expected: f64, id: OptionId| assert_eq!(expected, args.get_float(&id).unwrap().unwrap());

    assert_float(4_f64, option_id!(-'j', "jobs"));
    assert_float(3.14, option_id!("foo"));
    assert_float(1.137, option_id!("baz", "spam"));

    assert!(args.get_float(&option_id!("dne")).unwrap().is_none());

    assert_eq!(
        "Problem parsing --bad value swallow as a float value: invalid float literal".to_owned(),
        args.get_float(&option_id!("bad")).unwrap_err()
    );
}

#[test]
fn test_string_list() {
    let args = args([
        "--bad=['mis', 'matched')",
        "--phases=initial",
        "-p=['one']",
        "--phases=+['two','three'],-['one']",
    ]);

    assert_eq!(
        vec![
            ListEdit {
                action: ListEditAction::Add,
                items: vec!["initial".to_owned()]
            },
            ListEdit {
                action: ListEditAction::Replace,
                items: vec!["one".to_owned()]
            },
            ListEdit {
                action: ListEditAction::Add,
                items: vec!["two".to_owned(), "three".to_owned()]
            },
            ListEdit {
                action: ListEditAction::Remove,
                items: vec!["one".to_owned()]
            },
        ],
        args.get_string_list(&option_id!(-'p', "phases"))
            .unwrap()
            .unwrap()
    );

    assert!(args.get_string_list(&option_id!("dne")).unwrap().is_none());

    let expected_error_msg = "\
Problem parsing --bad string list value:
1:['mis', 'matched')
  -----------------^
Expected \",\" or the end of a list indicated by ']' at line 1 column 18"
        .to_owned();

    assert_eq!(
        expected_error_msg,
        args.get_string_list(&option_id!("bad")).unwrap_err()
    );
}
