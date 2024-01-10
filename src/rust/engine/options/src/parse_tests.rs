// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::parse::{parse_bool, parse_int_list, parse_string_list};
use crate::{ListEdit, ListEditAction};

#[test]
fn test_parse_bool() {
    assert_eq!(Ok(true), parse_bool("true"));
    assert_eq!(Ok(true), parse_bool("True"));
    assert_eq!(Ok(true), parse_bool("TRUE"));

    assert_eq!(Ok(false), parse_bool("false"));
    assert_eq!(Ok(false), parse_bool("False"));
    assert_eq!(Ok(false), parse_bool("FALSE"));

    assert_eq!(
        "Got '1' for foo. Expected 'true' or 'false'.".to_owned(),
        parse_bool("1").unwrap_err().render("foo")
    )
}

#[test]
fn test_parse_string_list_empty() {
    assert!(parse_string_list("").unwrap().is_empty());
}

#[test]
fn test_parse_int_list_empty() {
    assert!(parse_int_list("").unwrap().is_empty());
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

fn int_list_edit<I: IntoIterator<Item = i64>>(action: ListEditAction, items: I) -> ListEdit<i64> {
    ListEdit {
        action,
        items: items.into_iter().collect(),
    }
}

const EMPTY_STRING_LIST: [&str; 0] = [];
const EMPTY_INT_LIST: [i64; 0] = [];

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
fn test_parse_int_list_replace() {
    assert_eq!(
        vec![int_list_edit(ListEditAction::Replace, EMPTY_INT_LIST)],
        parse_int_list("[]").unwrap()
    );
    assert_eq!(
        vec![int_list_edit(ListEditAction::Replace, [42])],
        parse_int_list("[42]").unwrap()
    );
    assert_eq!(
        vec![int_list_edit(ListEditAction::Replace, [42, -127])],
        parse_int_list("[42,-127]").unwrap()
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
fn test_parse_int_list_add() {
    assert_eq!(
        vec![int_list_edit(ListEditAction::Add, EMPTY_INT_LIST)],
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
fn test_parse_int_list_remove() {
    assert_eq!(
        vec![int_list_edit(ListEditAction::Remove, EMPTY_INT_LIST)],
        parse_int_list("-[]").unwrap()
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
fn test_parse_int_list_edits() {
    assert_eq!(
        vec![
            int_list_edit(ListEditAction::Remove, [-3, 4]),
            int_list_edit(ListEditAction::Add, [42]),
            int_list_edit(ListEditAction::Remove, EMPTY_INT_LIST),
        ],
        parse_int_list("-[-3, 4],+[42],-[]").unwrap()
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
fn test_parse_int_list_edits_whitespace() {
    assert_eq!(
        vec![
            int_list_edit(ListEditAction::Remove, [42]),
            int_list_edit(ListEditAction::Add, [-127, 0]),
        ],
        parse_int_list(" - [ 42 , ] , + [ -127  ,0 ] ").unwrap()
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
fn test_parse_int_list_implicit_add() {
    assert_eq!(
        vec![int_list_edit(ListEditAction::Add, vec![999])],
        parse_int_list("999").unwrap()
    );
    assert_eq!(
        vec![int_list_edit(ListEditAction::Add, vec![0])],
        parse_int_list("0").unwrap()
    );
    assert_eq!(
        vec![int_list_edit(ListEditAction::Add, vec![-127])],
        parse_int_list("-127").unwrap()
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
fn test_parse_int_list_trailing_comma() {
    assert_eq!(
        vec![int_list_edit(ListEditAction::Replace, [42])],
        parse_int_list("[42,]").unwrap()
    );
    assert_eq!(
        vec![int_list_edit(ListEditAction::Replace, [42, -127])],
        parse_int_list("[42,-127,]").unwrap()
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
fn test_parse_int_list_whitespace() {
    assert_eq!(
        vec![int_list_edit(ListEditAction::Replace, [42])],
        parse_int_list(" [ 42 ] ").unwrap()
    );
    assert_eq!(
        vec![int_list_edit(ListEditAction::Replace, [42, -127])],
        parse_int_list(" [ 42 , -127 , ] ").unwrap()
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
fn test_parse_int_list_tuple() {
    assert_eq!(
        vec![int_list_edit(ListEditAction::Replace, EMPTY_INT_LIST)],
        parse_int_list("()").unwrap()
    );
    assert_eq!(
        vec![int_list_edit(ListEditAction::Replace, [42])],
        parse_int_list("(42)").unwrap()
    );
    assert_eq!(
        vec![int_list_edit(ListEditAction::Replace, [42, -127])],
        parse_int_list(r#" (42, -127,)"#).unwrap()
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
