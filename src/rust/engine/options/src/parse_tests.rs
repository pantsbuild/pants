// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::parse::test_util::write_fromfile;
use crate::parse::*;
use crate::{DictEdit, DictEditAction, ListEdit, ListEditAction, Val};
use maplit::hashmap;
use std::collections::HashMap;
use std::fmt::Debug;

// Helper macro (and associated functions) to print multiline parse errors.
// unwrap() and assert_eq! print the debug representation on error, which displays
// the multiline error message on one line, with escaped newlines.
// However our ParseError messages include a visual pointer to the error location,
// and so are much more useful when displayed multiline.

macro_rules! check {
    ($left:expr, $right:expr $(,)?) => { check($left, $right); };
    ($left:expr, $right:expr, $($arg:tt)+) => { check_with_arg($left, $right, $($arg)+); };
}

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

fn check<T: PartialEq + Debug>(expected: T, res: Result<T, ParseError>) {
    match res {
        Ok(actual) => assert_eq!(expected, actual),
        Err(s) => panic!("{}", s.render("test")),
    }
}

fn check_with_arg<T: PartialEq + Debug>(
    expected: T,
    res: Result<T, ParseError>,
    arg: &'static str,
) {
    match res {
        Ok(actual) => assert_eq!(expected, actual, "{}", arg),
        Err(s) => panic!("{}", s.render("test")),
    }
}

#[test]
fn test_parse_quoted_string() {
    fn check_str(expected: &str, input: &str) {
        // This is slightly convoluted: quoted strings appear as list items,
        // so we generate a list, and then extract the parsed string out of
        // the Result<Vec<ListEdit<String>>, ...> returned by parse_list().
        let parsed = String::parse_list(format!("[{}]", input).as_str())
            .unwrap()
            .first()
            .unwrap()
            .items
            .first()
            .unwrap()
            .to_string();
        check!(expected.to_string(), Ok(parsed));
    }

    check_str("", "''");
    check_str("", r#""""#);
    check_str("foo", "'foo'");
    check_str("foo", r#""foo""#);
    check_str("hanakapi'ai", r#"'hanakapi\'ai'"#);
    check_str("hanakapi'ai", r#""hanakapi'ai""#);
    check_str("bs\"d", r#""bs\"d""#);
    check_str("1995", r#""1995""#);
}

#[test]
fn test_parse_bool() {
    fn check_bool(expected: bool, input: &str) {
        check!(expected, bool::parse(input));
    }

    check_bool(true, "true");
    check_bool(true, "True");
    check_bool(true, "TRUE");

    check_bool(false, "false");
    check_bool(false, "False");
    check_bool(false, "FALSE");

    assert_eq!(
        "Problem parsing foo bool value:\n1:1\n  ^\nExpected 'true' or 'false' \
        at line 1 column 1"
            .to_owned(),
        bool::parse("1").unwrap_err().render("foo")
    )
}

#[test]
fn test_parse_int() {
    fn check_int(expected: i64, input: &str) {
        check!(expected, i64::parse(input));
    }
    check_int(0, "0");
    check_int(1, "1");
    check_int(1, "+1");
    check_int(-1, "-1");
    check_int(42, "42");
    check_int(999, "999");
    check_int(-123456789, "-123456789");
    check_int(-123456789, "-123_456_789");
    check_int(9223372036854775807, "9223372036854775807");
    check_int(-9223372036854775808, "-9223372036854775808");
    assert_eq!(
        "Problem parsing foo int value:\n1:badint\n  ^\nExpected \"+\", \"-\" or ['0'..='9'] \
               at line 1 column 1"
            .to_owned(),
        i64::parse("badint").unwrap_err().render("foo")
    );
    assert_eq!(
        "Problem parsing foo int value:\n1:12badint\n  --^\nExpected \"_\", EOF or ['0'..='9'] \
               at line 1 column 3"
            .to_owned(),
        i64::parse("12badint").unwrap_err().render("foo")
    );
}

#[test]
fn test_parse_float() {
    fn check_float(expected: f64, input: &str) {
        check!(expected, f64::parse(input));
    }
    check_float(0.0, "0.0");
    check_float(0.0, "-0.0");
    check_float(0.0, "0.");
    check_float(1.0, "1.0");
    check_float(0.1, "0.1");
    check_float(0.01, "+0.01");
    check_float(-98.101, "-98.101");
    check_float(-245678.1012, "-245_678.10_12");
    check_float(6.022141793e+23, "6.022141793e+23");
    check_float(5.67123e+11, "567.123e+9");
    check_float(9.1093837e-31, "9.1093837E-31");
}

#[test]
fn test_parse_list_from_empty_string() {
    assert!(String::parse_list("").unwrap().is_empty());
    assert!(bool::parse_list("").unwrap().is_empty());
    assert!(i64::parse_list("").unwrap().is_empty());
    assert!(f64::parse_list("").unwrap().is_empty());
}

fn string_list_edit<I: IntoIterator<Item = &'static str>>(
    action: ListEditAction,
    items: I,
) -> ListEdit<String> {
    ListEdit {
        action,
        items: items.into_iter().map(str::to_owned).collect(),
    }
}

fn scalar_list_edit<T, I: IntoIterator<Item = T>>(action: ListEditAction, items: I) -> ListEdit<T> {
    ListEdit {
        action,
        items: items.into_iter().collect(),
    }
}

const EMPTY_STRING_LIST: [&str; 0] = [];
const EMPTY_BOOL_LIST: [bool; 0] = [];
const EMPTY_INT_LIST: [i64; 0] = [];
const EMPTY_FLOAT_LIST: [f64; 0] = [];

#[test]
fn test_parse_string_list_replace() {
    check!(
        vec![string_list_edit(ListEditAction::Replace, EMPTY_STRING_LIST)],
        String::parse_list("[]")
    );
    check!(
        vec![string_list_edit(ListEditAction::Replace, ["foo"])],
        String::parse_list("['foo']")
    );
    check!(
        vec![string_list_edit(ListEditAction::Replace, ["foo", "bar"])],
        String::parse_list("['foo','bar']")
    );
}

#[test]
fn test_parse_bool_list_replace() {
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, EMPTY_BOOL_LIST)],
        bool::parse_list("[]")
    );
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, [true])],
        bool::parse_list("[True]")
    );
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, [true, false])],
        bool::parse_list("[True,FALSE]")
    );
}

#[test]
fn test_parse_int_list_replace() {
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, EMPTY_INT_LIST)],
        i64::parse_list("[]")
    );
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, [42])],
        i64::parse_list("[42]")
    );
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, [42, -127])],
        i64::parse_list("[42,-127]")
    );
}

#[test]
fn test_parse_float_list_replace() {
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, EMPTY_FLOAT_LIST)],
        f64::parse_list("[]")
    );
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, [123456.78])],
        f64::parse_list("[123_456.78]")
    );
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, [42.0, -1.27e+7])],
        f64::parse_list("[42.0,-127.0e+5]")
    );
}

#[test]
fn test_parse_string_list_add() {
    check!(
        vec![string_list_edit(ListEditAction::Add, EMPTY_STRING_LIST)],
        String::parse_list("+[]")
    );
}

#[test]
fn test_parse_scalar_list_add() {
    check!(
        vec![scalar_list_edit(ListEditAction::Add, EMPTY_INT_LIST)],
        i64::parse_list("+[]")
    );
}

#[test]
fn test_parse_string_list_remove() {
    check!(
        vec![string_list_edit(ListEditAction::Remove, EMPTY_STRING_LIST)],
        String::parse_list("-[]")
    );
}

#[test]
fn test_parse_scalar_list_remove() {
    check!(
        vec![scalar_list_edit(ListEditAction::Remove, EMPTY_BOOL_LIST)],
        bool::parse_list("-[]")
    );
}

#[test]
fn test_parse_string_list_edits() {
    check!(
        vec![
            string_list_edit(ListEditAction::Remove, ["foo", "bar"]),
            string_list_edit(ListEditAction::Add, ["baz"]),
            string_list_edit(ListEditAction::Remove, EMPTY_STRING_LIST),
        ],
        String::parse_list("-['foo', 'bar'],+['baz'],-[]")
    );
}

#[test]
fn test_parse_bool_list_edits() {
    check!(
        vec![
            scalar_list_edit(ListEditAction::Remove, [true, false]),
            scalar_list_edit(ListEditAction::Add, [false]),
            scalar_list_edit(ListEditAction::Remove, EMPTY_BOOL_LIST),
        ],
        bool::parse_list("-[True, FALSE],+[false],-[]")
    );
}

#[test]
fn test_parse_int_list_edits() {
    check!(
        vec![
            scalar_list_edit(ListEditAction::Remove, [-3, 4]),
            scalar_list_edit(ListEditAction::Add, [42]),
            scalar_list_edit(ListEditAction::Remove, EMPTY_INT_LIST),
        ],
        i64::parse_list("-[-3, 4],+[42],-[]")
    );
}

#[test]
fn test_parse_float_list_edits() {
    check!(
        vec![
            scalar_list_edit(ListEditAction::Remove, [-3.0, 4.1]),
            scalar_list_edit(ListEditAction::Add, [42.7]),
            scalar_list_edit(ListEditAction::Remove, EMPTY_FLOAT_LIST),
        ],
        f64::parse_list("-[-3.0, 4.1],+[42.7],-[]")
    );
}

#[test]
fn test_parse_string_list_edits_whitespace() {
    check!(
        vec![
            string_list_edit(ListEditAction::Remove, ["foo"]),
            string_list_edit(ListEditAction::Add, ["bar"]),
        ],
        String::parse_list(" - [ 'foo' , ] ,\n + [ 'bar' ] ")
    );
}

#[test]
fn test_parse_scalar_list_edits_whitespace() {
    check!(
        vec![
            scalar_list_edit(ListEditAction::Remove, [42.0]),
            scalar_list_edit(ListEditAction::Add, [-127.1, 0.0]),
        ],
        f64::parse_list(" - [ 42.0 , ] , + [ -127.1  ,0. ] ")
    );
}

#[test]
fn test_parse_string_list_implicit_add() {
    check!(
        vec![string_list_edit(ListEditAction::Add, vec!["foo"])],
        String::parse_list("foo")
    );
    check!(
        vec![string_list_edit(ListEditAction::Add, vec!["foo bar"])],
        String::parse_list("foo bar")
    );
    check!(
        vec![string_list_edit(ListEditAction::Add, ["--bar"])],
        String::parse_list("--bar")
    );
}

#[test]
fn test_parse_scalar_list_implicit_add() {
    check!(
        vec![scalar_list_edit(ListEditAction::Add, vec![true])],
        bool::parse_list("True")
    );
    check!(
        vec![scalar_list_edit(ListEditAction::Add, vec![-127])],
        i64::parse_list("-127")
    );
    check!(
        vec![scalar_list_edit(ListEditAction::Add, vec![0.7])],
        f64::parse_list("0.7")
    );
}

#[test]
fn test_parse_string_list_quoted_chars() {
    check!(
        vec![string_list_edit(ListEditAction::Add, vec!["[]"])],
        String::parse_list(r"\[]"),
        "Expected an implicit add of the literal string `[]` via an escaped opening `[`."
    );
    check!(
        vec![string_list_edit(ListEditAction::Add, vec![" "])],
        String::parse_list(r"\ "),
        "Expected an implicit add of the literal string ` `."
    );
    check!(
        vec![string_list_edit(ListEditAction::Add, vec!["+"])],
        String::parse_list(r"\+"),
        "Expected an implicit add of the literal string `+`."
    );
    check!(
        vec![string_list_edit(ListEditAction::Add, vec!["-"])],
        String::parse_list(r"\-"),
        "Expected an implicit add of the literal string `-`."
    );
    check!(
        vec![string_list_edit(
            ListEditAction::Replace,
            vec!["'foo", r"\"]
        )],
        String::parse_list(r"['\'foo', '\\']")
    );
}

#[test]
fn test_parse_string_list_quote_forms() {
    check!(
        vec![string_list_edit(ListEditAction::Replace, ["foo"])],
        String::parse_list(r#"["foo"]"#),
        "Expected double quotes to work."
    );
    check!(
        vec![string_list_edit(ListEditAction::Replace, ["foo", "bar"])],
        String::parse_list(r#"["foo", 'bar']"#),
        "Expected mixed quote forms to work."
    );
}

#[test]
fn test_parse_string_list_trailing_comma() {
    check!(
        vec![string_list_edit(ListEditAction::Replace, ["foo"])],
        String::parse_list("['foo',]")
    );
    check!(
        vec![string_list_edit(ListEditAction::Replace, ["foo", "bar"])],
        String::parse_list("['foo','bar',]")
    );
}

#[test]
fn test_parse_scalar_list_trailing_comma() {
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, [false, true])],
        bool::parse_list("[false,true,]")
    );
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, [42])],
        i64::parse_list("[42,]")
    );
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, [42.0, -127.1])],
        f64::parse_list("[42.0,-127.1,]")
    );
}

#[test]
fn test_parse_string_list_whitespace() {
    check!(
        vec![string_list_edit(ListEditAction::Replace, ["foo"])],
        String::parse_list(" [ 'foo' ] ")
    );
    check!(
        vec![string_list_edit(ListEditAction::Replace, ["foo", "bar"])],
        String::parse_list(" [ 'foo' , 'bar' , ] ")
    );
}

#[test]
fn test_parse_scalar_list_whitespace() {
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, [true, false])],
        bool::parse_list("  [  True,  False  ] ")
    );
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, [42])],
        i64::parse_list(" [ 42 ] ")
    );
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, [42.0, -127.1])],
        f64::parse_list(" [ 42.0 , -127.1 , ] ")
    );
}

#[test]
fn test_parse_string_list_tuple() {
    check!(
        vec![string_list_edit(ListEditAction::Replace, EMPTY_STRING_LIST)],
        String::parse_list("()")
    );
    check!(
        vec![string_list_edit(ListEditAction::Replace, ["foo"])],
        String::parse_list(r#"("foo")"#)
    );
    check!(
        vec![string_list_edit(ListEditAction::Replace, ["foo", "bar"])],
        String::parse_list(r#" ('foo', "bar",)"#)
    );
}

#[test]
fn test_parse_scalar_list_tuple() {
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, EMPTY_INT_LIST)],
        i64::parse_list("()")
    );
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, [true])],
        bool::parse_list("(True)")
    );
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, [42.0, -127.1])],
        f64::parse_list(r#" (42.0, -127.1,)"#)
    );
}

#[test]
fn test_parse_string_list_error_formatting() {
    let bad_input = "\
-['/etc/hosts'],
         ?(\"/dev/null\")
";

    let expected_error_msg = "\
Problem parsing foo string list value:
1:-['/etc/hosts'],
2:         ?(\"/dev/null\")
  ---------^
3:
Expected an optional list edit action of '+' indicating `add` \
or '-' indicating `remove` at line 2 column 10"
        .to_owned();
    assert_eq!(
        expected_error_msg,
        String::parse_list(bad_input).unwrap_err().render("foo")
    )
}

#[test]
fn test_parse_int_list_error_formatting() {
    let bad_input = "\
-[42],
         ?(127,0)
";

    let expected_error_msg = "\
Problem parsing foo int list value:
1:-[42],
2:         ?(127,0)
  ---------^
3:
Expected an optional list edit action of '+' indicating `add` \
or '-' indicating `remove` at line 2 column 10"
        .to_owned();
    assert_eq!(
        expected_error_msg,
        i64::parse_list(bad_input).unwrap_err().render("foo")
    )
}

fn mk_hashmap(items: &Vec<(&str, &str)>) -> HashMap<String, Val> {
    HashMap::<_, _>::from_iter(
        items
            .iter()
            .map(|(k, v)| (k.to_string(), Val::String(v.to_string()))),
    )
}

fn mk_dict_edit(action: DictEditAction, items: &Vec<(&str, &str)>) -> DictEdit {
    DictEdit {
        action,
        items: mk_hashmap(items),
    }
}

#[test]
fn test_parse_dict_empty() {
    check!(
        mk_dict_edit(DictEditAction::Replace, &vec![]),
        parse_dict("{}")
    );
}

#[test]
fn test_parse_dict_simple() {
    check!(
        mk_dict_edit(
            DictEditAction::Replace,
            &vec![("foo", "bar"), ("baz", "qux")]
        ),
        parse_dict(r#"{'foo': "bar", "baz": 'qux'}"#)
    );
}

#[test]
fn test_parse_dict_add() {
    check!(
        mk_dict_edit(DictEditAction::Add, &vec![("foo", "bar"), ("baz", "qux")]),
        parse_dict(r#"+{'foo': "bar", "baz": 'qux'}"#)
    );
}

#[test]
fn test_parse_dict_whitespace() {
    check!(
        mk_dict_edit(
            DictEditAction::Replace,
            &vec![("foo", "bar"), ("baz", "qux")]
        ),
        parse_dict(
            r#" {  'foo' :'bar'  ,
        'baz'  :    'qux'  }  "#
        )
    );
}

#[test]
fn test_parse_dict_of_list_of_string() {
    let mut expected = HashMap::<String, Val>::new();
    expected.insert(
        "foo".to_string(),
        Val::List(vec![
            Val::String("foo1".to_string()),
            Val::String("foo2".to_string()),
        ]),
    );
    expected.insert(
        "bar".to_string(),
        Val::List(vec![Val::String("bar1".to_string())]),
    );
    expected.insert("baz".to_string(), Val::List(vec![]));

    check!(
        DictEdit {
            action: DictEditAction::Add,
            items: expected
        },
        parse_dict(r#" +{'foo': ["foo1", 'foo2'], "bar" : ('bar1' ,), "baz": []} "#)
    );
}

#[test]
fn test_parse_heterogeneous_dict() {
    let mut nested = HashMap::<String, Val>::new();
    nested.insert("x".to_string(), Val::Float(3.14));
    nested.insert(
        "y".to_string(),
        Val::List(vec![Val::String("y1".to_string())]),
    );
    let mut expected = HashMap::<String, Val>::new();
    expected.insert(
        "foo".to_string(),
        Val::List(vec![Val::Int(42), Val::String("foo1".to_string())]),
    );
    expected.insert(
        "bar".to_string(),
        Val::List(vec![
            Val::String("bar1".to_string()),
            Val::Bool(true),
            Val::List(vec![]),
        ]),
    );
    expected.insert("baz".to_string(), Val::Dict(nested));

    check!(
        DictEdit {
            action: DictEditAction::Replace,
            items: expected
        },
        parse_dict(
            r#"
        {
          "foo": [42, 'foo1'],
          "bar" : ('bar1' , true, []),
          'baz': {
            'x': 3.14,
            'y': ["y1",],
          },
        }
        "#
        )
    );
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
