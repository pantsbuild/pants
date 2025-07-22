// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::arg_splitter::ArgSplitter;
use crate::arg_splitter::Args;
use crate::flags::FlagsReader;
use crate::fromfile::FromfileExpander;
use crate::fromfile::test_util::write_fromfile;
use crate::{DictEdit, DictEditAction, GoalInfo, Scope, Val, option_id};
use crate::{ListEdit, ListEditAction, OptionId, OptionsSource};
use core::fmt::Debug;
use maplit::hashmap;
use tempfile::TempDir;

fn mk_args<I>(args: I) -> FlagsReader
where
    I: IntoIterator,
    I::Item: ToString,
{
    let command = ArgSplitter::new(
        TempDir::new().unwrap().path(),
        vec![
            GoalInfo::new("scope", false, false, vec![]),
            GoalInfo::new("lunch", false, false, vec![]),
        ],
    );
    FlagsReader::new(
        command
            .split_args(Args::new(args.into_iter().map(|s| s.to_string())))
            .flags,
        FromfileExpander::relative_to_cwd(),
    )
}

#[test]
fn test_display() {
    let args = mk_args::<Vec<&str>>(vec![]);
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
        "--unladen-capacity=swallow",
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
    assert_string("swallow", option_id!("unladen", "capacity"));
    assert_string("debug", option_id!(-'l', "level"));
    assert_string("qux", option_id!(["scope"], "qux"));
    assert_string("quux", option_id!(["scope"], "quux"));

    assert!(args.get_string(&option_id!("dne")).unwrap().is_none());
}

#[test]
fn test_bool() {
    let args = mk_args([
        "--unladen-capacity=swallow",
        "--foo=false",
        "--foo",
        "--no-bar",
        "--baz=true",
        "--baz=FALSE",
        "--no-spam-eggs=False",
        "--scope-quxt",
        "--no-scope-quxf",
        "scope",
        "--no-quuxf",
        "--quuxt",
        "path/to/target",
        "--global-flag",
    ]);

    let assert_bool =
        |expected: bool, id: OptionId| assert_eq!(expected, args.get_bool(&id).unwrap().unwrap());

    assert_bool(true, option_id!("foo"));
    assert_bool(false, option_id!("bar"));
    assert_bool(false, option_id!("baz"));
    assert_bool(true, option_id!("spam", "eggs"));
    assert_bool(true, option_id!(["scope"], "quxt"));
    assert_bool(false, option_id!(["scope"], "quxf"));
    assert_bool(false, option_id!(["scope"], "quuxf"));
    assert_bool(true, option_id!(["scope"], "quuxt"));
    assert_bool(true, option_id!("global", "flag"));

    assert!(args.get_bool(&option_id!("dne")).unwrap().is_none());
    assert_eq!(
        "Problem parsing --unladen-capacity bool value:\n1:swallow\n  ^\nExpected 'true' or 'false' at line 1 column 1".to_owned(),
        args.get_bool(&option_id!("unladen", "capacity"))
            .unwrap_err()
    );
}

#[test]
fn test_float() {
    let args = mk_args([
        "--jobs=4",
        "--foo=42",
        "--foo=3.14",
        "--baz-spam=1.137",
        "--bad=swallow",
    ]);

    let assert_float =
        |expected: f64, id: OptionId| assert_eq!(expected, args.get_float(&id).unwrap().unwrap());

    assert_float(4_f64, option_id!("jobs"));
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
        "--phases=['one']",
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
        args.get_string_list(&option_id!("phases"))
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
        getter: fn(&FlagsReader, &OptionId) -> Result<Option<T>, String>,
        negate: bool,
    ) {
        let (_tmpdir, fromfile_path) = write_fromfile("fromfile.txt", content);
        let args = mk_args(vec![
            format!(
                "--{}foo=@{}",
                if negate { "no-" } else { "" },
                fromfile_path.display()
            )
            .as_str(),
        ]);
        let actual = getter(&args, &option_id!("foo")).unwrap().unwrap();
        assert_eq!(expected, actual)
    }

    do_test("true", true, FlagsReader::get_bool, false);
    do_test("false", false, FlagsReader::get_bool, false);
    do_test("true", false, FlagsReader::get_bool, true);
    do_test("false", true, FlagsReader::get_bool, true);
    do_test("-42", -42, FlagsReader::get_int, false);
    do_test("3.14", 3.14, FlagsReader::get_float, false);
    do_test(
        "EXPANDED",
        "EXPANDED".to_owned(),
        FlagsReader::get_string,
        false,
    );

    let (_tmpdir, fromfile_path) = write_fromfile("fromfile.txt", "BAD INT");
    let args = mk_args(vec![format!("--foo=@{}", fromfile_path.display())]);
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
        let args = mk_args(vec![
            format!("--foo=@{}", &fromfile_path.display()).as_str(),
        ]);
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
        "+[-42]",
        &[ListEdit {
            action: ListEditAction::Add,
            items: vec![-42],
        }],
        "fromfile.txt",
    );
    do_test(
        "[-42]",
        &[ListEdit {
            action: ListEditAction::Replace,
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
        let args = mk_args(vec![
            &format!("--foo=@{}", &fromfile_path.display()),
            "--foo=+{'KEY':'VALUE'}",
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

    // Test adding, rather than replacing, from a raw text fromfile.
    let expected_add = vec![DictEdit {
        action: DictEditAction::Add,
        items: hashmap! {"FOO".to_string() => Val::Int(42)},
    }];

    let (_tmpdir, fromfile_path) = write_fromfile("fromfile.txt", "+{'FOO':42}");
    let args = mk_args(vec![
        format!("--foo=@{}", &fromfile_path.display()).as_str(),
    ]);
    assert_eq!(
        expected_add,
        args.get_dict(&option_id!("foo")).unwrap().unwrap()
    )
}

#[test]
fn test_nonexistent_required_fromfile() {
    let args = mk_args(vec!["--foo=@/does/not/exist"]);
    let err = args.get_string(&option_id!("foo")).unwrap_err();
    assert!(
        err.starts_with("Problem reading /does/not/exist for --foo: No such file or directory")
    );
}

#[test]
fn test_nonexistent_optional_fromfile() {
    let args = mk_args(vec!["--foo=@?/does/not/exist"]);
    assert!(args.get_string(&option_id!("foo")).unwrap().is_none());
}

#[test]
fn test_tracker() {
    let args = mk_args([
        "-ldebug",
        "--scope-flag1",
        "--foo=bar",
        "--no-scope-flag2",
        "scope",
        "--baz-qux",
    ]);

    assert_eq!(
        hashmap! {
            Scope::Global => vec![
                "--foo".to_string(),
                "--no-scope-flag2".to_string(),
                "--scope-flag1".to_string(),
                "-l".to_string()
            ],
            Scope::named("scope") => vec![
                "--baz-qux".to_string(),
            ],
        },
        args.get_tracker().get_unconsumed_flags()
    );

    args.get_string(&option_id!("foo")).unwrap();
    assert_eq!(
        hashmap! {
            Scope::Global => vec![
                "--no-scope-flag2".to_string(),
                "--scope-flag1".to_string(),
                "-l".to_string()
            ],
            Scope::named("scope") => vec![
                "--baz-qux".to_string(),
            ],
        },
        args.get_tracker().get_unconsumed_flags()
    );

    args.get_bool(&option_id!(["scope"], "baz", "qux")).unwrap();
    assert_eq!(
        hashmap! {
            Scope::Global => vec![
                "--no-scope-flag2".to_string(),
                "--scope-flag1".to_string(),
                "-l".to_string(),
            ],
        },
        args.get_tracker().get_unconsumed_flags()
    );

    args.get_string(&option_id!(-'l', "level")).unwrap();
    assert_eq!(
        hashmap! {
            Scope::Global => vec![
                "--no-scope-flag2".to_string(),
                "--scope-flag1".to_string(),
            ],
        },
        args.get_tracker().get_unconsumed_flags()
    );

    args.get_bool(&option_id!(["scope"], "flag1")).unwrap();
    assert_eq!(
        hashmap! {
            Scope::Global => vec![
                "--no-scope-flag2".to_string(),
            ],
        },
        args.get_tracker().get_unconsumed_flags()
    );

    args.get_bool(&option_id!(["scope"], "flag2")).unwrap();
    assert_eq!(hashmap! {}, args.get_tracker().get_unconsumed_flags());
}
