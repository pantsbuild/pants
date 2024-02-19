// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::parse::*;
use crate::{DictEdit, DictEditAction, ListEdit, ListEditAction, Val};
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
        check!(expected.to_string(), parse_quoted_string(input));
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
        check!(expected, parse_bool(input));
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
        parse_bool("1").unwrap_err().render("foo")
    )
}

#[test]
fn test_parse_int() {
    fn check_int(expected: i64, input: &str) {
        check!(expected, parse_int(input));
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
        parse_int("badint").unwrap_err().render("foo")
    );
    assert_eq!(
        "Problem parsing foo int value:\n1:12badint\n  --^\nExpected \"_\", EOF or ['0'..='9'] \
               at line 1 column 3"
            .to_owned(),
        parse_int("12badint").unwrap_err().render("foo")
    );
}

#[test]
fn test_parse_float() {
    fn check_float(expected: f64, input: &str) {
        check!(expected, parse_float(input));
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
    assert!(parse_string_list("").unwrap().is_empty());
    assert!(parse_bool_list("").unwrap().is_empty());
    assert!(parse_int_list("").unwrap().is_empty());
    assert!(parse_float_list("").unwrap().is_empty());
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
        parse_string_list("[]")
    );
    check!(
        vec![string_list_edit(ListEditAction::Replace, ["foo"])],
        parse_string_list("['foo']")
    );
    check!(
        vec![string_list_edit(ListEditAction::Replace, ["foo", "bar"])],
        parse_string_list("['foo','bar']")
    );
}

#[test]
fn test_parse_bool_list_replace() {
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, EMPTY_BOOL_LIST)],
        parse_bool_list("[]")
    );
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, [true])],
        parse_bool_list("[True]")
    );
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, [true, false])],
        parse_bool_list("[True,FALSE]")
    );
}

#[test]
fn test_parse_int_list_replace() {
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, EMPTY_INT_LIST)],
        parse_int_list("[]")
    );
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, [42])],
        parse_int_list("[42]")
    );
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, [42, -127])],
        parse_int_list("[42,-127]")
    );
}

#[test]
fn test_parse_float_list_replace() {
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, EMPTY_FLOAT_LIST)],
        parse_float_list("[]")
    );
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, [123456.78])],
        parse_float_list("[123_456.78]")
    );
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, [42.0, -1.27e+7])],
        parse_float_list("[42.0,-127.0e+5]")
    );
}

#[test]
fn test_parse_string_list_add() {
    check!(
        vec![string_list_edit(ListEditAction::Add, EMPTY_STRING_LIST)],
        parse_string_list("+[]")
    );
}

#[test]
fn test_parse_scalar_list_add() {
    check!(
        vec![scalar_list_edit(ListEditAction::Add, EMPTY_INT_LIST)],
        parse_int_list("+[]")
    );
}

#[test]
fn test_parse_string_list_remove() {
    check!(
        vec![string_list_edit(ListEditAction::Remove, EMPTY_STRING_LIST)],
        parse_string_list("-[]")
    );
}

#[test]
fn test_parse_scalar_list_remove() {
    check!(
        vec![scalar_list_edit(ListEditAction::Remove, EMPTY_BOOL_LIST)],
        parse_bool_list("-[]")
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
        parse_string_list("-['foo', 'bar'],+['baz'],-[]")
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
        parse_bool_list("-[True, FALSE],+[false],-[]")
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
        parse_int_list("-[-3, 4],+[42],-[]")
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
        parse_float_list("-[-3.0, 4.1],+[42.7],-[]")
    );
}

#[test]
fn test_parse_string_list_edits_whitespace() {
    check!(
        vec![
            string_list_edit(ListEditAction::Remove, ["foo"]),
            string_list_edit(ListEditAction::Add, ["bar"]),
        ],
        parse_string_list(" - [ 'foo' , ] ,\n + [ 'bar' ] ")
    );
}

#[test]
fn test_parse_scalar_list_edits_whitespace() {
    check!(
        vec![
            scalar_list_edit(ListEditAction::Remove, [42.0]),
            scalar_list_edit(ListEditAction::Add, [-127.1, 0.0]),
        ],
        parse_float_list(" - [ 42.0 , ] , + [ -127.1  ,0. ] ")
    );
}

#[test]
fn test_parse_string_list_implicit_add() {
    check!(
        vec![string_list_edit(ListEditAction::Add, vec!["foo"])],
        parse_string_list("foo")
    );
    check!(
        vec![string_list_edit(ListEditAction::Add, vec!["foo bar"])],
        parse_string_list("foo bar")
    );
    check!(
        vec![string_list_edit(ListEditAction::Add, ["--bar"])],
        parse_string_list("--bar")
    );
}

#[test]
fn test_parse_scalar_list_implicit_add() {
    check!(
        vec![scalar_list_edit(ListEditAction::Add, vec![true])],
        parse_bool_list("True")
    );
    check!(
        vec![scalar_list_edit(ListEditAction::Add, vec![-127])],
        parse_int_list("-127")
    );
    check!(
        vec![scalar_list_edit(ListEditAction::Add, vec![0.7])],
        parse_float_list("0.7")
    );
}

#[test]
fn test_parse_string_list_quoted_chars() {
    check!(
        vec![string_list_edit(ListEditAction::Add, vec!["[]"])],
        parse_string_list(r"\[]"),
        "Expected an implicit add of the literal string `[]` via an escaped opening `[`."
    );
    check!(
        vec![string_list_edit(ListEditAction::Add, vec![" "])],
        parse_string_list(r"\ "),
        "Expected an implicit add of the literal string ` `."
    );
    check!(
        vec![string_list_edit(ListEditAction::Add, vec!["+"])],
        parse_string_list(r"\+"),
        "Expected an implicit add of the literal string `+`."
    );
    check!(
        vec![string_list_edit(ListEditAction::Add, vec!["-"])],
        parse_string_list(r"\-"),
        "Expected an implicit add of the literal string `-`."
    );
    check!(
        vec![string_list_edit(
            ListEditAction::Replace,
            vec!["'foo", r"\"]
        )],
        parse_string_list(r"['\'foo', '\\']")
    );
}

#[test]
fn test_parse_string_list_quote_forms() {
    check!(
        vec![string_list_edit(ListEditAction::Replace, ["foo"])],
        parse_string_list(r#"["foo"]"#),
        "Expected double quotes to work."
    );
    check!(
        vec![string_list_edit(ListEditAction::Replace, ["foo", "bar"])],
        parse_string_list(r#"["foo", 'bar']"#),
        "Expected mixed quote forms to work."
    );
}

#[test]
fn test_parse_string_list_trailing_comma() {
    check!(
        vec![string_list_edit(ListEditAction::Replace, ["foo"])],
        parse_string_list("['foo',]")
    );
    check!(
        vec![string_list_edit(ListEditAction::Replace, ["foo", "bar"])],
        parse_string_list("['foo','bar',]")
    );
}

#[test]
fn test_parse_scalar_list_trailing_comma() {
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, [false, true])],
        parse_bool_list("[false,true,]")
    );
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, [42])],
        parse_int_list("[42,]")
    );
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, [42.0, -127.1])],
        parse_float_list("[42.0,-127.1,]")
    );
}

#[test]
fn test_parse_string_list_whitespace() {
    check!(
        vec![string_list_edit(ListEditAction::Replace, ["foo"])],
        parse_string_list(" [ 'foo' ] ")
    );
    check!(
        vec![string_list_edit(ListEditAction::Replace, ["foo", "bar"])],
        parse_string_list(" [ 'foo' , 'bar' , ] ")
    );
}

#[test]
fn test_parse_scalar_list_whitespace() {
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, [true, false])],
        parse_bool_list("  [  True,  False  ] ")
    );
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, [42])],
        parse_int_list(" [ 42 ] ")
    );
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, [42.0, -127.1])],
        parse_float_list(" [ 42.0 , -127.1 , ] ")
    );
}

#[test]
fn test_parse_string_list_tuple() {
    check!(
        vec![string_list_edit(ListEditAction::Replace, EMPTY_STRING_LIST)],
        parse_string_list("()")
    );
    check!(
        vec![string_list_edit(ListEditAction::Replace, ["foo"])],
        parse_string_list(r#"("foo")"#)
    );
    check!(
        vec![string_list_edit(ListEditAction::Replace, ["foo", "bar"])],
        parse_string_list(r#" ('foo', "bar",)"#)
    );
}

#[test]
fn test_parse_scalar_list_tuple() {
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, EMPTY_INT_LIST)],
        parse_int_list("()")
    );
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, [true])],
        parse_bool_list("(True)")
    );
    check!(
        vec![scalar_list_edit(ListEditAction::Replace, [42.0, -127.1])],
        parse_float_list(r#" (42.0, -127.1,)"#)
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
        parse_string_list(bad_input).unwrap_err().render("foo")
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
        parse_int_list(bad_input).unwrap_err().render("foo")
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
