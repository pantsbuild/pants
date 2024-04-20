// Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::fromfile::test_util::write_fromfile;
use crate::fromfile::*;
use crate::parse::{ParseError, Parseable};
use crate::{DictEdit, DictEditAction, ListEdit, ListEditAction, Val};
use maplit::hashmap;
use std::collections::HashMap;
use std::fmt::Debug;

macro_rules! check_err {
    ($res:expr, $expected_suffix:expr $(,)?) => {
        let actual_msg = $res.unwrap_err().render("XXX");
        assert!(
            actual_msg.ends_with($expected_suffix),
            "Error message does not have expected suffix:\n{actual_msg}\nvs\n{:>width$}",
            $expected_suffix,
            width = actual_msg.len(),
        )
    };
}

fn expand(value: String) -> Result<Option<String>, ParseError> {
    FromfileExpander::new().expand(value)
}

fn expand_to_list<T: Parseable>(value: String) -> Result<Option<Vec<ListEdit<T>>>, ParseError> {
    FromfileExpander::new().expand_to_list(value)
}

fn expand_to_dict(value: String) -> Result<Option<Vec<DictEdit>>, ParseError> {
    FromfileExpander::new().expand_to_dict(value)
}

#[test]
fn test_expand_fromfile() {
    let (_tmpdir, fromfile_pathbuf) = write_fromfile("fromfile.txt", "FOO");
    let fromfile_path_str = format!("{}", fromfile_pathbuf.display());
    assert_eq!(
        Ok(Some(fromfile_path_str.clone())),
        expand(fromfile_path_str.clone())
    );
    assert_eq!(
        Ok(Some("FOO".to_string())),
        expand(format!("@{}", fromfile_path_str))
    );
    assert_eq!(Ok(None), expand("@?/does/not/exist".to_string()));
    let err = expand("@/does/not/exist".to_string()).unwrap_err();
    assert!(err
        .render("XXX")
        .starts_with("Problem reading /does/not/exist for XXX: No such file or directory"))
}

#[test]
fn test_expand_fromfile_to_list() {
    fn expand_fromfile<T: Parseable + Clone + Debug + PartialEq>(
        content: &str,
        prefix: &str,
        filename: &str,
    ) -> Result<Option<Vec<ListEdit<T>>>, ParseError> {
        let (_tmpdir, _) = write_fromfile(filename, content);
        expand_to_list(format!(
            "{prefix}{}",
            _tmpdir.path().join(filename).display()
        ))
    }

    fn do_test<T: Parseable + Clone + Debug + PartialEq>(
        content: &str,
        expected: &[ListEdit<T>],
        filename: &str,
    ) {
        let res = expand_fromfile(content, "@", filename);
        assert_eq!(expected.to_vec(), res.unwrap().unwrap());
    }

    fn add<T>(items: Vec<T>) -> ListEdit<T> {
        return ListEdit {
            action: ListEditAction::Add,
            items: items,
        };
    }

    fn remove<T>(items: Vec<T>) -> ListEdit<T> {
        return ListEdit {
            action: ListEditAction::Remove,
            items: items,
        };
    }

    fn replace<T>(items: Vec<T>) -> ListEdit<T> {
        return ListEdit {
            action: ListEditAction::Replace,
            items: items,
        };
    }

    do_test(
        "EXPANDED",
        &[add(vec!["EXPANDED".to_string()])],
        "fromfile.txt",
    );
    do_test(
        "['FOO', 'BAR']",
        &[replace(vec!["FOO".to_string(), "BAR".to_string()])],
        "fromfile.txt",
    );
    do_test(
        "+['FOO', 'BAR'],-['BAZ']",
        &[
            add(vec!["FOO".to_string(), "BAR".to_string()]),
            remove(vec!["BAZ".to_string()]),
        ],
        "fromfile.txt",
    );
    do_test(
        "[\"FOO\", \"BAR\"]",
        &[replace(vec!["FOO".to_string(), "BAR".to_string()])],
        "fromfile.json",
    );
    do_test(
        "- FOO\n- BAR\n",
        &[replace(vec!["FOO".to_string(), "BAR".to_string()])],
        "fromfile.yaml",
    );

    do_test("true", &[add(vec![true])], "fromfile.txt");
    do_test(
        "[true, false]",
        &[replace(vec![true, false])],
        "fromfile.json",
    );
    do_test(
        "- true\n- false\n",
        &[replace(vec![true, false])],
        "fromfile.yaml",
    );

    do_test("-42", &[add(vec![-42])], "fromfile.txt");
    do_test("[10, 12]", &[replace(vec![10, 12])], "fromfile.json");
    do_test("- 22\n- 44\n", &[replace(vec![22, 44])], "fromfile.yaml");

    do_test("-5.6", &[add(vec![-5.6])], "fromfile.txt");
    do_test("-[3.14]", &[remove(vec![3.14])], "fromfile.txt");
    do_test("[3.14]", &[replace(vec![3.14])], "fromfile.json");
    do_test(
        "- 11.22\n- 33.44\n",
        &[replace(vec![11.22, 33.44])],
        "fromfile.yaml",
    );

    check_err!(
        expand_fromfile::<i64>("THIS IS NOT JSON", "@", "invalid.json"),
        "expected value at line 1 column 1",
    );

    check_err!(
        expand_fromfile::<i64>("{}", "@", "wrong_type.json"),
        "invalid type: map, expected a sequence at line 1 column 0",
    );

    check_err!(
        expand_fromfile::<i64>("[1, \"FOO\"]", "@", "wrong_type.json"),
        "invalid type: string \"FOO\", expected i64 at line 1 column 9",
    );

    check_err!(
        expand_fromfile::<i64>("THIS IS NOT YAML", "@", "invalid.yml"),
        "invalid type: string \"THIS IS NOT YAML\", expected a sequence",
    );

    check_err!(
        expand_fromfile::<i64>("- 1\n- true", "@", "wrong_type.yaml"),
        "invalid type: boolean `true`, expected i64 at line 2 column 3",
    );

    check_err!(
        expand_to_list::<String>("@/does/not/exist".to_string()),
        "Problem reading /does/not/exist for XXX: No such file or directory (os error 2)",
    );

    assert_eq!(
        Ok(None),
        expand_to_list::<String>("@?/does/not/exist".to_string())
    );

    // Test an optional fromfile that does exist, to ensure we handle the `?` in this case.
    let res = expand_fromfile::<i64>("[1, 2]", "@?", "fromfile.json");
    assert_eq!(vec![replace(vec![1, 2])], res.unwrap().unwrap());
}

#[test]
fn test_expand_fromfile_to_dict() {
    fn expand_fromfile(
        content: &str,
        prefix: &str,
        filename: &str,
    ) -> Result<Option<DictEdit>, ParseError> {
        let (_tmpdir, _) = write_fromfile(filename, content);
        expand_to_dict(format!(
            "{prefix}{}",
            _tmpdir.path().join(filename).display()
        ))
        .map(|x| {
            if let Some(des) = x {
                des.into_iter().next()
            } else {
                None
            }
        })
    }

    fn do_test(content: &str, expected: &DictEdit, filename: &str) {
        let res = expand_fromfile(content, "@", filename);
        assert_eq!(*expected, res.unwrap().unwrap())
    }

    fn add(items: HashMap<String, Val>) -> DictEdit {
        return DictEdit {
            action: DictEditAction::Add,
            items,
        };
    }

    fn replace(items: HashMap<String, Val>) -> DictEdit {
        return DictEdit {
            action: DictEditAction::Replace,
            items,
        };
    }

    do_test(
        "{'FOO': 42}",
        &replace(hashmap! {"FOO".to_string() => Val::Int(42),}),
        "fromfile.txt",
    );

    do_test(
        "+{'FOO': [True, False]}",
        &add(hashmap! {"FOO".to_string() => Val::List(vec![Val::Bool(true), Val::Bool(false)]),}),
        "fromfile.txt",
    );

    let complex_obj = replace(hashmap! {
    "FOO".to_string() => Val::Dict(hashmap! {
        "BAR".to_string() => Val::Float(3.14),
        "BAZ".to_string() => Val::Dict(hashmap! {
            "QUX".to_string() => Val::Bool(true),
            "QUUX".to_string() => Val::List(vec![ Val::Int(1), Val::Int(2)])
        })
    }),});

    do_test(
        "{\"FOO\": {\"BAR\": 3.14, \"BAZ\": {\"QUX\": true, \"QUUX\": [1, 2]}}}",
        &complex_obj,
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
        &complex_obj,
        "fromfile.yaml",
    );

    check_err!(
        expand_fromfile("THIS IS NOT JSON", "@", "invalid.json"),
        "expected value at line 1 column 1",
    );

    check_err!(
        expand_fromfile("[1, 2]", "@", "wrong_type.json"),
        "invalid type: sequence, expected a map at line 1 column 0",
    );

    check_err!(
        expand_fromfile("THIS IS NOT YAML", "@", "invalid.yml"),
        "invalid type: string \"THIS IS NOT YAML\", expected a map",
    );

    check_err!(
        expand_fromfile("- 1\n- 2", "@", "wrong_type.yaml"),
        "invalid type: sequence, expected a map",
    );

    check_err!(
        expand_to_dict("@/does/not/exist".to_string()),
        "Problem reading /does/not/exist for XXX: No such file or directory (os error 2)",
    );

    assert_eq!(Ok(None), expand_to_dict("@?/does/not/exist".to_string()));

    // Test an optional fromfile that does exist, to ensure we handle the `?` in this case.
    let res = expand_fromfile("{'FOO': 42}", "@?", "fromfile.txt");
    assert_eq!(
        replace(hashmap! {"FOO".to_string() => Val::Int(42),}),
        res.unwrap().unwrap()
    );
}
