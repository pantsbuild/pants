// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use core::fmt::Debug;
use maplit::hashmap;

use crate::args::Args;
use crate::parse::test_util::write_fromfile;
use crate::{option_id, DictEdit, DictEditAction, Val};
use crate::{ListEdit, ListEditAction, OptionId, OptionsSource};

fn mk_args<I: IntoIterator<Item = &'static str>>(args: I) -> Args {
    Args::new(args.into_iter().map(str::to_owned))
}

#[test]
fn test_display() {
    let args = mk_args([]);
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
    let args = mk_args([
        "-u=swallow",
        "-ldebug",
        "--foo=bar",
        "--baz-spam=eggs",
        "--baz-spam=cheese",
        "--scope-qux=qux",
        "scope",
        "--quux=quux",
    ]);

    let assert_string = |expected: &str, id: OptionId| {
        assert_eq!(expected.to_owned(), args.get_string(&id).unwrap().unwrap())
    };

    assert_string("bar", option_id!("foo"));
    assert_string("cheese", option_id!("baz", "spam"));
    assert_string("swallow", option_id!(-'u', "unladen", "capacity"));
    assert_string("debug", option_id!(-'l', "level"));
    assert_string("qux", option_id!(["scope"], "qux"));
    assert_string("quux", option_id!(["scope"], "quux"));

    assert!(args.get_string(&option_id!("dne")).unwrap().is_none());
}

#[test]
fn test_bool() {
    let args = mk_args([
        "-c=swallow",
        "--foo=false",
        "-f",
        "--no-bar",
        "--baz=true",
        "--baz=FALSE",
        "--no-spam-eggs=False",
        "--scope-quxt",
        "--no-scope-quxf",
        "scope",
        "--no-quuxf",
        "--quuxt",
    ]);

    let assert_bool =
        |expected: bool, id: OptionId| assert_eq!(expected, args.get_bool(&id).unwrap().unwrap());

    assert_bool(true, option_id!(-'f', "foo"));
    assert_bool(false, option_id!("bar"));
    assert_bool(false, option_id!(-'b', "baz"));
    assert_bool(true, option_id!("spam", "eggs"));
    assert_bool(true, option_id!(["scope"], "quxt"));
    assert_bool(false, option_id!(["scope"], "quxf"));
    assert_bool(false, option_id!(["scope"], "quuxf"));
    assert_bool(true, option_id!(["scope"], "quuxt"));

    assert!(args.get_bool(&option_id!("dne")).unwrap().is_none());
    assert_eq!(
        "Problem parsing -c bool value:\n1:swallow\n  ^\nExpected 'true' or 'false' at line 1 column 1".to_owned(),
        args.get_bool(&option_id!(-'c', "unladen", "capacity"))
            .unwrap_err()
    );
}

#[test]
fn test_float() {
    let args = mk_args([
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
        "Problem parsing --bad float value:\n1:swallow\n  ^\n\
        Expected \"+\", \"-\" or ['0'..='9'] at line 1 column 1"
            .to_owned(),
        args.get_float(&option_id!("bad")).unwrap_err()
    );
}

#[test]
fn test_string_list() {
    let args = mk_args([
        "--bad=['mis', 'matched')",
        "--phases=initial",
        "-p=['one']",
        "--phases=+['two','three'],-['one']",
        "--lunch-veggies=['tomatoes', 'peppers']",
        "lunch",
        "--veggies=+['cucumbers']",
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

    assert_eq!(
        vec![
            ListEdit {
                action: ListEditAction::Replace,
                items: vec!["tomatoes".to_owned(), "peppers".to_owned()]
            },
            ListEdit {
                action: ListEditAction::Add,
                items: vec!["cucumbers".to_owned()]
            },
        ],
        args.get_string_list(&option_id!(["lunch"], "veggies"))
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

#[test]
fn test_scalar_fromfile() {
    fn do_test<T: PartialEq + Debug>(
        content: &str,
        expected: T,
        getter: fn(&Args, &OptionId) -> Result<Option<T>, String>,
        negate: bool,
    ) {
        let (_tmpdir, fromfile_path) = write_fromfile("fromfile.txt", content);
        let args = Args::new(vec![format!(
            "--{}foo=@{}",
            if negate { "no-" } else { "" },
            fromfile_path.display()
        )]);
        let actual = getter(&args, &option_id!("foo")).unwrap().unwrap();
        assert_eq!(expected, actual)
    }

    do_test("true", true, Args::get_bool, false);
    do_test("false", false, Args::get_bool, false);
    do_test("true", false, Args::get_bool, true);
    do_test("false", true, Args::get_bool, true);
    do_test("-42", -42, Args::get_int, false);
    do_test("3.14", 3.14, Args::get_float, false);
    do_test("EXPANDED", "EXPANDED".to_owned(), Args::get_string, false);

    let (_tmpdir, fromfile_path) = write_fromfile("fromfile.txt", "BAD INT");
    let args = Args::new(vec![format!("--foo=@{}", fromfile_path.display())]);
    assert_eq!(
        args.get_int(&option_id!("foo")).unwrap_err(),
        "Problem parsing --foo int value:\n1:BAD INT\n  ^\n\
               Expected \"+\", \"-\" or ['0'..='9'] at line 1 column 1"
    );
}

#[test]
fn test_list_fromfile() {
    fn do_test(content: &str, expected: &[ListEdit<i64>], filename: &str) {
        let (_tmpdir, fromfile_path) = write_fromfile(filename, content);
        let args = Args::new(vec![format!("--foo=@{}", &fromfile_path.display())]);
        let actual = args.get_int_list(&option_id!("foo")).unwrap().unwrap();
        assert_eq!(expected.to_vec(), actual)
    }

    do_test(
        "-42",
        &[ListEdit {
            action: ListEditAction::Add,
            items: vec![-42],
        }],
        "fromfile.txt",
    );
    do_test(
        "[10, 12]",
        &[ListEdit {
            action: ListEditAction::Replace,
            items: vec![10, 12],
        }],
        "fromfile.json",
    );
    do_test(
        "- 22\n- 44\n",
        &[ListEdit {
            action: ListEditAction::Replace,
            items: vec![22, 44],
        }],
        "fromfile.yaml",
    );
}

#[test]
fn test_dict_fromfile() {
    fn do_test(content: &str, filename: &str) {
        let expected = vec![
            DictEdit {
                action: DictEditAction::Replace,
                items: hashmap! {
                "FOO".to_string() => Val::Dict(hashmap! {
                    "BAR".to_string() => Val::Float(3.14),
                    "BAZ".to_string() => Val::Dict(hashmap! {
                        "QUX".to_string() => Val::Bool(true),
                        "QUUX".to_string() => Val::List(vec![ Val::Int(1), Val::Int(2)])
                    })
                }),},
            },
            DictEdit {
                action: DictEditAction::Add,
                items: hashmap! {
                    "KEY".to_string() => Val::String("VALUE".to_string()),
                },
            },
        ];

        let (_tmpdir, fromfile_path) = write_fromfile(filename, content);
        let args = Args::new(vec![
            format!("--foo=@{}", &fromfile_path.display()),
            "--foo=+{'KEY':'VALUE'}".to_string(),
        ]);
        let actual = args.get_dict(&option_id!("foo")).unwrap().unwrap();
        assert_eq!(expected, actual)
    }

    do_test(
        "{'FOO': {'BAR': 3.14, 'BAZ': {'QUX': True, 'QUUX': [1, 2]}}}",
        "fromfile.txt",
    );
    do_test(
        "{\"FOO\": {\"BAR\": 3.14, \"BAZ\": {\"QUX\": true, \"QUUX\": [1, 2]}}}",
        "fromfile.json",
    );
    do_test(
        r#"
        FOO:
          BAR: 3.14
          BAZ:
            QUX: true
            QUUX:
              - 1
              - 2
        "#,
        "fromfile.yaml",
    );
}

#[test]
fn test_nonexistent_required_fromfile() {
    let args = Args::new(vec!["--foo=@/does/not/exist".to_string()]);
    let err = args.get_string(&option_id!("foo")).unwrap_err();
    assert!(err.starts_with("Problem reading /does/not/exist for --foo: No such file or directory"));
}

#[test]
fn test_nonexistent_optional_fromfile() {
    let args = Args::new(vec!["--foo=@?/does/not/exist".to_string()]);
    assert!(args.get_string(&option_id!("foo")).unwrap().is_none());
}
