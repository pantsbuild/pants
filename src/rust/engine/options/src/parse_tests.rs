// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::parse::*;
use crate::{ListEdit, ListEditAction};

#[test]
fn test_parse_quoted_string() {
    fn check(expected: &str, input: &str) {
        assert_eq!(Ok(expected.to_string()), parse_quoted_string(input));
    }
    check("", "''");
    check("", r#""""#);
    check("foo", "'foo'");
    check("foo", r#""foo""#);
    check("hanakapi'ai", r#"'hanakapi\'ai'"#);
    check("hanakapi'ai", r#""hanakapi'ai""#);
    check("bs\"d", r#""bs\"d""#);
    check("1995", r#""1995""#);
}

#[test]
fn test_parse_bool() {
    assert_eq!(Ok(true), parse_bool("true"));
    assert_eq!(Ok(true), parse_bool("True"));
    assert_eq!(Ok(true), parse_bool("TRUE"));

    assert_eq!(Ok(false), parse_bool("false"));
    assert_eq!(Ok(false), parse_bool("False"));
    assert_eq!(Ok(false), parse_bool("FALSE"));

    assert_eq!(
        "Problem parsing foo bool value:\n1:1\n  ^\nExpected 'true' or 'false' \
        at line 1 column 1"
            .to_owned(),
        parse_bool("1").unwrap_err().render("foo")
    )
}

#[test]
fn test_parse_int() {
    assert_eq!(Ok(0), parse_int("0"));
    assert_eq!(Ok(1), parse_int("1"));
    assert_eq!(Ok(1), parse_int("+1"));
    assert_eq!(Ok(-1), parse_int("-1"));
    assert_eq!(Ok(42), parse_int("42"));
    assert_eq!(Ok(999), parse_int("999"));
    assert_eq!(Ok(-123456789), parse_int("-123456789"));
    assert_eq!(Ok(-123456789), parse_int("-123_456_789"));
    assert_eq!(Ok(9223372036854775807), parse_int("9223372036854775807"));
    assert_eq!(Ok(-9223372036854775808), parse_int("-9223372036854775808"));
    assert_eq!(
        "Problem parsing foo int value:\n1:badint\n  ^\nExpected \"+\", \"-\" or ['0' ..= '9'] \
               at line 1 column 1"
            .to_owned(),
        parse_int("badint").unwrap_err().render("foo")
    );
    assert_eq!(
        "Problem parsing foo int value:\n1:12badint\n  --^\nExpected \"_\", EOF or ['0' ..= '9'] \
               at line 1 column 3"
            .to_owned(),
        parse_int("12badint").unwrap_err().render("foo")
    );
}

#[test]
fn test_parse_float() {
    assert_eq!(Ok(0.0), parse_float("0.0"));
    assert_eq!(Ok(0.0), parse_float("-0.0"));
    assert_eq!(Ok(0.0), parse_float("0."));
    assert_eq!(Ok(1.0), parse_float("1.0"));
    assert_eq!(Ok(0.1), parse_float("0.1"));
    assert_eq!(Ok(0.01), parse_float("+0.01"));
    assert_eq!(Ok(-98.101), parse_float("-98.101"));
    assert_eq!(Ok(-245678.1012), parse_float("-245_678.10_12"));
    assert_eq!(Ok(6.022141793e+23), parse_float("6.022141793e+23"));
    assert_eq!(Ok(5.67123e+11), parse_float("567.123e+9"));
    assert_eq!(Ok(9.1093837e-31), parse_float("9.1093837E-31"));
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
    assert_eq!(
        vec![string_list_edit(ListEditAction::Replace, EMPTY_STRING_LIST)],
        parse_string_list("[]").unwrap()
    );
    assert_eq!(
        vec![string_list_edit(ListEditAction::Replace, ["foo"])],
        parse_string_list("['foo']").unwrap()
    );
    assert_eq!(
        vec![string_list_edit(ListEditAction::Replace, ["foo", "bar"])],
        parse_string_list("['foo','bar']").unwrap()
    );
}

#[test]
fn test_parse_bool_list_replace() {
    assert_eq!(
        vec![scalar_list_edit(ListEditAction::Replace, EMPTY_BOOL_LIST)],
        parse_bool_list("[]").unwrap()
    );
    assert_eq!(
        vec![scalar_list_edit(ListEditAction::Replace, [true])],
        parse_bool_list("[True]").unwrap()
    );
    assert_eq!(
        vec![scalar_list_edit(ListEditAction::Replace, [true, false])],
        parse_bool_list("[True,FALSE]").unwrap()
    );
}

#[test]
fn test_parse_int_list_replace() {
    assert_eq!(
        vec![scalar_list_edit(ListEditAction::Replace, EMPTY_INT_LIST)],
        parse_int_list("[]").unwrap()
    );
    assert_eq!(
        vec![scalar_list_edit(ListEditAction::Replace, [42])],
        parse_int_list("[42]").unwrap()
    );
    assert_eq!(
        vec![scalar_list_edit(ListEditAction::Replace, [42, -127])],
        parse_int_list("[42,-127]").unwrap()
    );
}

#[test]
fn test_parse_float_list_replace() {
    assert_eq!(
        vec![scalar_list_edit(ListEditAction::Replace, EMPTY_FLOAT_LIST)],
        parse_float_list("[]").unwrap()
    );
    assert_eq!(
        vec![scalar_list_edit(ListEditAction::Replace, [123456.78])],
        parse_float_list("[123_456.78]").unwrap()
    );
    assert_eq!(
        vec![scalar_list_edit(ListEditAction::Replace, [42.0, -1.27e+7])],
        parse_float_list("[42.0,-127.0e+5]").unwrap()
    );
}

#[test]
fn test_parse_string_list_add() {
    assert_eq!(
        vec![string_list_edit(ListEditAction::Add, EMPTY_STRING_LIST)],
        parse_string_list("+[]").unwrap()
    );
}

#[test]
fn test_parse_scalar_list_add() {
    assert_eq!(
        vec![scalar_list_edit(ListEditAction::Add, EMPTY_INT_LIST)],
        parse_int_list("+[]").unwrap()
    );
}

#[test]
fn test_parse_string_list_remove() {
    assert_eq!(
        vec![string_list_edit(ListEditAction::Remove, EMPTY_STRING_LIST)],
        parse_string_list("-[]").unwrap()
    );
}

#[test]
fn test_parse_scalar_list_remove() {
    assert_eq!(
        vec![scalar_list_edit(ListEditAction::Remove, EMPTY_BOOL_LIST)],
        parse_bool_list("-[]").unwrap()
    );
}

#[test]
fn test_parse_string_list_edits() {
    assert_eq!(
        vec![
            string_list_edit(ListEditAction::Remove, ["foo", "bar"]),
            string_list_edit(ListEditAction::Add, ["baz"]),
            string_list_edit(ListEditAction::Remove, EMPTY_STRING_LIST),
        ],
        parse_string_list("-['foo', 'bar'],+['baz'],-[]").unwrap()
    );
}

#[test]
fn test_parse_bool_list_edits() {
    assert_eq!(
        vec![
            scalar_list_edit(ListEditAction::Remove, [true, false]),
            scalar_list_edit(ListEditAction::Add, [false]),
            scalar_list_edit(ListEditAction::Remove, EMPTY_BOOL_LIST),
        ],
        parse_bool_list("-[True, FALSE],+[false],-[]").unwrap()
    );
}

#[test]
fn test_parse_int_list_edits() {
    assert_eq!(
        vec![
            scalar_list_edit(ListEditAction::Remove, [-3, 4]),
            scalar_list_edit(ListEditAction::Add, [42]),
            scalar_list_edit(ListEditAction::Remove, EMPTY_INT_LIST),
        ],
        parse_int_list("-[-3, 4],+[42],-[]").unwrap()
    );
}

#[test]
fn test_parse_float_list_edits() {
    assert_eq!(
        vec![
            scalar_list_edit(ListEditAction::Remove, [-3.0, 4.1]),
            scalar_list_edit(ListEditAction::Add, [42.7]),
            scalar_list_edit(ListEditAction::Remove, EMPTY_FLOAT_LIST),
        ],
        parse_float_list("-[-3.0, 4.1],+[42.7],-[]").unwrap()
    );
}

#[test]
fn test_parse_string_list_edits_whitespace() {
    assert_eq!(
        vec![
            string_list_edit(ListEditAction::Remove, ["foo"]),
            string_list_edit(ListEditAction::Add, ["bar"]),
        ],
        parse_string_list(" - [ 'foo' , ] , + [ 'bar' ] ").unwrap()
    );
}

#[test]
fn test_parse_scalar_list_edits_whitespace() {
    assert_eq!(
        vec![
            scalar_list_edit(ListEditAction::Remove, [42.0]),
            scalar_list_edit(ListEditAction::Add, [-127.1, 0.0]),
        ],
        parse_float_list(" - [ 42.0 , ] , + [ -127.1  ,0. ] ").unwrap()
    );
}

#[test]
fn test_parse_string_list_implicit_add() {
    assert_eq!(
        vec![string_list_edit(ListEditAction::Add, vec!["foo"])],
        parse_string_list("foo").unwrap()
    );
    assert_eq!(
        vec![string_list_edit(ListEditAction::Add, vec!["foo bar"])],
        parse_string_list("foo bar").unwrap()
    );
    assert_eq!(
        vec![string_list_edit(ListEditAction::Add, ["--bar"])],
        parse_string_list("--bar").unwrap()
    );
}

#[test]
fn test_parse_scalar_list_implicit_add() {
    assert_eq!(
        vec![scalar_list_edit(ListEditAction::Add, vec![true])],
        parse_bool_list("True").unwrap()
    );
    assert_eq!(
        vec![scalar_list_edit(ListEditAction::Add, vec![-127])],
        parse_int_list("-127").unwrap()
    );
    assert_eq!(
        vec![scalar_list_edit(ListEditAction::Add, vec![0.7])],
        parse_float_list("0.7").unwrap()
    );
}

#[test]
fn test_parse_string_list_quoted_chars() {
    assert_eq!(
        vec![string_list_edit(ListEditAction::Add, vec!["[]"])],
        parse_string_list(r"\[]").unwrap(),
        "Expected an implicit add of the literal string `[]` via an escaped opening `[`."
    );
    assert_eq!(
        vec![string_list_edit(ListEditAction::Add, vec![" "])],
        parse_string_list(r"\ ").unwrap(),
        "Expected an implicit add of the literal string ` `."
    );
    assert_eq!(
        vec![string_list_edit(ListEditAction::Add, vec!["+"])],
        parse_string_list(r"\+").unwrap(),
        "Expected an implicit add of the literal string `+`."
    );
    assert_eq!(
        vec![string_list_edit(ListEditAction::Add, vec!["-"])],
        parse_string_list(r"\-").unwrap(),
        "Expected an implicit add of the literal string `-`."
    );
    assert_eq!(
        vec![string_list_edit(
            ListEditAction::Replace,
            vec!["'foo", r"\"]
        )],
        parse_string_list(r"['\'foo', '\\']").unwrap()
    );
}

#[test]
fn test_parse_string_list_quote_forms() {
    assert_eq!(
        vec![string_list_edit(ListEditAction::Replace, ["foo"])],
        parse_string_list(r#"["foo"]"#).unwrap(),
        "Expected double quotes to work."
    );
    assert_eq!(
        vec![string_list_edit(ListEditAction::Replace, ["foo", "bar"])],
        parse_string_list(r#"["foo", 'bar']"#).unwrap(),
        "Expected mixed quote forms to work."
    );
}

#[test]
fn test_parse_string_list_trailing_comma() {
    assert_eq!(
        vec![string_list_edit(ListEditAction::Replace, ["foo"])],
        parse_string_list("['foo',]").unwrap()
    );
    assert_eq!(
        vec![string_list_edit(ListEditAction::Replace, ["foo", "bar"])],
        parse_string_list("['foo','bar',]").unwrap()
    );
}

#[test]
fn test_parse_scalar_list_trailing_comma() {
    assert_eq!(
        vec![scalar_list_edit(ListEditAction::Replace, [false, true])],
        parse_bool_list("[false,true,]").unwrap()
    );
    assert_eq!(
        vec![scalar_list_edit(ListEditAction::Replace, [42])],
        parse_int_list("[42,]").unwrap()
    );
    assert_eq!(
        vec![scalar_list_edit(ListEditAction::Replace, [42.0, -127.1])],
        parse_float_list("[42.0,-127.1,]").unwrap()
    );
}

#[test]
fn test_parse_string_list_whitespace() {
    assert_eq!(
        vec![string_list_edit(ListEditAction::Replace, ["foo"])],
        parse_string_list(" [ 'foo' ] ").unwrap()
    );
    assert_eq!(
        vec![string_list_edit(ListEditAction::Replace, ["foo", "bar"])],
        parse_string_list(" [ 'foo' , 'bar' , ] ").unwrap()
    );
}

#[test]
fn test_parse_scalar_list_whitespace() {
    assert_eq!(
        vec![scalar_list_edit(ListEditAction::Replace, [true, false])],
        parse_bool_list("  [  True,  False  ] ").unwrap()
    );
    assert_eq!(
        vec![scalar_list_edit(ListEditAction::Replace, [42])],
        parse_int_list(" [ 42 ] ").unwrap()
    );
    assert_eq!(
        vec![scalar_list_edit(ListEditAction::Replace, [42.0, -127.1])],
        parse_float_list(" [ 42.0 , -127.1 , ] ").unwrap()
    );
}

#[test]
fn test_parse_string_list_tuple() {
    assert_eq!(
        vec![string_list_edit(ListEditAction::Replace, EMPTY_STRING_LIST)],
        parse_string_list("()").unwrap()
    );
    assert_eq!(
        vec![string_list_edit(ListEditAction::Replace, ["foo"])],
        parse_string_list(r#"("foo")"#).unwrap()
    );
    assert_eq!(
        vec![string_list_edit(ListEditAction::Replace, ["foo", "bar"])],
        parse_string_list(r#" ('foo', "bar",)"#).unwrap()
    );
}

#[test]
fn test_parse_scalar_list_tuple() {
    assert_eq!(
        vec![scalar_list_edit(ListEditAction::Replace, EMPTY_INT_LIST)],
        parse_int_list("()").unwrap()
    );
    assert_eq!(
        vec![scalar_list_edit(ListEditAction::Replace, [true])],
        parse_bool_list("(True)").unwrap()
    );
    assert_eq!(
        vec![scalar_list_edit(ListEditAction::Replace, [42.0, -127.1])],
        parse_float_list(r#" (42.0, -127.1,)"#).unwrap()
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
