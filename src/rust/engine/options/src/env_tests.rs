// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::env::{Env, EnvReader};
use crate::fromfile::test_util::write_fromfile;
use crate::fromfile::FromfileExpander;
use crate::{option_id, DictEdit, DictEditAction};
use crate::{ListEdit, ListEditAction, OptionId, OptionsSource, Val};
use maplit::hashmap;
use std::collections::HashMap;
use std::ffi::OsString;
use std::fmt::Debug;

fn env<'a, I: IntoIterator<Item = (&'a str, &'a str)>>(vars: I) -> EnvReader {
    EnvReader::new(
        Env::new(
            vars.into_iter()
                .map(|(k, v)| (k.to_owned(), v.to_owned()))
                .collect::<HashMap<_, _>>(),
        ),
        FromfileExpander::relative_to_cwd(),
    )
}

#[test]
#[cfg(not(target_os = "windows"))]
fn test_capture_lossy() {
    // OsString::from_vec(Vec[u8]) requires unix.
    use std::os::unix::ffi::OsStringExt;

    let fake_vars: Vec<(OsString, OsString)> = vec![
        ("GOOD_KEY1".into(), "GOOD_VALUE".into()),
        (
            OsString::from_vec(b"BAD_\xa5KEY".to_vec()),
            "GOOD_VALUE".into(),
        ),
        (
            "GOOD_KEY2".into(),
            OsString::from_vec(b"BAD_\xa5VALUE".to_vec()),
        ),
    ];
    let (env, dropped) = Env::do_capture_lossy(fake_vars.into_iter());
    let captured_vars: Vec<(String, String)> = (&env).into();
    assert_eq!(
        captured_vars,
        vec![(String::from("GOOD_KEY1"), String::from("GOOD_VALUE"))]
    );
    assert_eq!(
        dropped.non_utf8_keys,
        vec![OsString::from_vec(b"BAD_\xa5KEY".to_vec())]
    );
    assert_eq!(
        dropped.keys_with_non_utf8_values,
        vec![String::from("GOOD_KEY2")]
    );
}

#[test]
fn test_display() {
    let env = env([]);
    assert_eq!("PANTS_NAME".to_owned(), env.display(&option_id!("name")));
    assert_eq!(
        "PANTS_SCOPE_NAME".to_owned(),
        env.display(&option_id!(["scope"], "name"))
    );
    assert_eq!(
        "PANTS_SCOPE_FULL_NAME".to_owned(),
        env.display(&option_id!(-'f', ["scope"], "full", "name"))
    );
}

#[test]
fn test_scope() {
    let env = env([("PANTS_PYTHON_EXAMPLE", "true")]);
    assert!(env
        .get_bool(&option_id!(["python"], "example"))
        .unwrap()
        .unwrap());
}

#[test]
fn test_string() {
    let env = env([
        ("PANTS_FOO", "bar"),
        ("PANTS_BAZ_SPAM", "cheese"),
        ("PANTS_EGGS", "swallow"),
        ("PANTS_GLOBAL_BOB", "African"),
        ("PANTS_PANTS_JANE", "elderberry"),
    ]);

    let assert_string = |expected: &str, id: OptionId| {
        assert_eq!(expected.to_owned(), env.get_string(&id).unwrap().unwrap())
    };

    assert_string("bar", option_id!("foo"));
    assert_string("cheese", option_id!("baz", "spam"));
    assert_string("swallow", option_id!("pants", "eggs"));
    assert_string("African", option_id!("bob"));
    assert_string("elderberry", option_id!("pants", "jane"));

    assert!(env.get_string(&option_id!("dne")).unwrap().is_none());
}

#[test]
fn test_bool() {
    let env = env([
        ("PANTS_FOO", "true"),
        ("PANTS_BAR_BAZ", "False"),
        ("PANTS_EGGS", "swallow"),
    ]);

    let assert_bool =
        |expected: bool, id: OptionId| assert_eq!(expected, env.get_bool(&id).unwrap().unwrap());

    assert_bool(true, option_id!("foo"));
    assert_bool(false, option_id!("bar", "baz"));

    assert!(env.get_bool(&option_id!("dne")).unwrap().is_none());
    assert_eq!(
        "Problem parsing PANTS_EGGS bool value:\n1:swallow\n  ^\nExpected 'true' or 'false' \
        at line 1 column 1"
            .to_owned(),
        env.get_bool(&option_id!("pants", "eggs")).unwrap_err()
    );
}

#[test]
fn test_float() {
    let env = env([
        ("PANTS_FOO", "4"),
        ("PANTS_BAR_BAZ", "3.14"),
        ("PANTS_EGGS", "1.137"),
        ("PANTS_BAD", "swallow"),
    ]);

    let assert_float =
        |expected: f64, id: OptionId| assert_eq!(expected, env.get_float(&id).unwrap().unwrap());

    assert_float(4_f64, option_id!("foo"));
    assert_float(3.14, option_id!("bar", "baz"));
    assert_float(1.137, option_id!("pants", "eggs"));

    assert!(env.get_float(&option_id!("dne")).unwrap().is_none());

    assert_eq!(
        "Problem parsing PANTS_BAD float value:\n1:swallow\n  ^\n\
        Expected \"+\", \"-\" or ['0'..='9'] at line 1 column 1"
            .to_owned(),
        env.get_float(&option_id!("pants", "bad")).unwrap_err()
    );
}

#[test]
fn test_string_list() {
    let env = env([
        ("PANTS_BAD", "('mis', 'matched']"),
        ("PANTS_IMPLICIT_ADD", "initial"),
        ("PANTS_RESET", "['one']"),
        ("PANTS_EDITS", "+['two','three'],-['one']"),
    ]);

    let get_string_list = |id| env.get_string_list(&id).unwrap().unwrap();

    assert_eq!(
        vec![ListEdit {
            action: ListEditAction::Add,
            items: vec!["initial".to_owned()]
        },],
        get_string_list(option_id!("implicit", "add"))
    );

    assert_eq!(
        vec![ListEdit {
            action: ListEditAction::Replace,
            items: vec!["one".to_owned()]
        },],
        get_string_list(option_id!("reset"))
    );

    assert_eq!(
        vec![
            ListEdit {
                action: ListEditAction::Add,
                items: vec!["two".to_owned(), "three".to_owned()]
            },
            ListEdit {
                action: ListEditAction::Remove,
                items: vec!["one".to_owned()]
            },
        ],
        get_string_list(option_id!("edits"))
    );

    assert!(env.get_string_list(&option_id!("dne")).unwrap().is_none());

    let expected_error_msg = "\
Problem parsing PANTS_BAD string list value:
1:('mis', 'matched']
  -----------------^
Expected \",\" or the end of a tuple indicated by ')' at line 1 column 18"
        .to_owned();

    assert_eq!(
        expected_error_msg,
        env.get_string_list(&option_id!("bad")).unwrap_err()
    );
}

#[test]
fn test_scalar_fromfile() {
    fn do_test<T: PartialEq + Debug>(
        content: &str,
        expected: T,
        getter: fn(&EnvReader, &OptionId) -> Result<Option<T>, String>,
    ) {
        let (_tmpdir, fromfile_path) = write_fromfile("fromfile.txt", content);
        let env = env([(
            "PANTS_FOO",
            format!("@{}", fromfile_path.display()).as_str(),
        )]);
        let actual = getter(&env, &option_id!("foo")).unwrap().unwrap();
        assert_eq!(expected, actual)
    }

    do_test("true", true, EnvReader::get_bool);
    do_test("-42", -42, EnvReader::get_int);
    do_test("3.14", 3.14, EnvReader::get_float);
    do_test("EXPANDED", "EXPANDED".to_owned(), EnvReader::get_string);
}

#[test]
fn test_list_fromfile() {
    fn do_test(content: &str, expected: &[ListEdit<i64>], filename: &str) {
        let (_tmpdir, fromfile_path) = write_fromfile(filename, content);
        let env = env([(
            "PANTS_FOO",
            format!("@{}", fromfile_path.display()).as_str(),
        )]);
        let actual = env.get_int_list(&option_id!("foo")).unwrap().unwrap();
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
        let expected = vec![DictEdit {
            action: DictEditAction::Replace,
            items: hashmap! {
            "FOO".to_string() => Val::Dict(hashmap! {
                "BAR".to_string() => Val::Float(3.14),
                "BAZ".to_string() => Val::Dict(hashmap! {
                    "QUX".to_string() => Val::Bool(true),
                    "QUUX".to_string() => Val::List(vec![ Val::Int(1), Val::Int(2)])
                })
            }),},
        }];

        let (_tmpdir, fromfile_path) = write_fromfile(filename, content);
        let env = env([(
            "PANTS_FOO",
            format!("@{}", fromfile_path.display()).as_str(),
        )]);
        let actual = env.get_dict(&option_id!("foo")).unwrap().unwrap();
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
    let env = env([("PANTS_FOO", "@/does/not/exist")]);
    let err = env.get_string(&option_id!("foo")).unwrap_err();
    assert!(
        err.starts_with("Problem reading /does/not/exist for PANTS_FOO: No such file or directory")
    );
}

#[test]
fn test_nonexistent_optional_fromfile() {
    let env = env([("PANTS_FOO", "@?/does/not/exist")]);
    assert!(env.get_string(&option_id!("foo")).unwrap().is_none());
}
