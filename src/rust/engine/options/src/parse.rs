// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use super::{ListEdit, ListEditAction};
use crate::render_choice;

peg::parser! {
    grammar option_value_parser() for str {
        use peg::ParseLiteral;

        rule whitespace() -> ()
            = quiet!{ " " / "\n" / "\r" / "\t" }

        rule string() -> String
            = s:(non_escaped_character() / escaped_character())+ { s.into_iter().collect() }

        rule non_escaped_character() -> char
            = !"\\" c:$([_]) { c.chars().next().unwrap() }

        rule quoted_string() -> String
            = whitespace()*
            string:(double_quoted_string() / single_quoted_string())
            whitespace()* { string }

        rule double_quoted_string() -> String
            = "\"" s:double_quoted_character()* "\"" { s.into_iter().collect() }

        rule double_quoted_character() -> char
            = quoted_character("\"")
            / escaped_character()

        rule single_quoted_string() -> String
            = "'" s:single_quoted_character()* "'" { s.into_iter().collect() }

        rule single_quoted_character() -> char
            = quoted_character("'")
            / escaped_character()

        rule quoted_character(quote_char: &'static str) -> char
            = !(##parse_string_literal(quote_char) / "\\") c:$([_]) { c.chars().next().unwrap() }

        rule escaped_character() -> char
            = "\\" c:$([_]) { c.chars().next().unwrap() }

        rule add() -> ListEditAction
            = "+" { ListEditAction::Add }

        rule remove() -> ListEditAction
            = "-" { ListEditAction::Remove }

        rule action() -> ListEditAction
            = quiet!{ action:(add() / remove()) { action } }
            / expected!(
                "an optional list edit action of '+' indicating `add` or '-' indicating `remove`"
            )

        // N.B.: The Python list parsing implementation accepts Python tuple literal syntax too.

        rule tuple_start() -> ()
            = quiet!{ "(" }
            / expected!("the start of a tuple indicated by '('")

        rule tuple_end() -> ()
            = quiet!{ ")" }
            / expected!("the end of a tuple indicated by ')'")

        rule tuple_items() -> Vec<String>
            = tuple_start()
            items:quoted_string() ** ","
            whitespace()* ","? whitespace()*
            tuple_end() {
                items
            }

        rule list_start() -> ()
            = quiet!{ "[" }
            / expected!("the start of a list indicated by '['")

        rule list_end() -> ()
            = quiet!{ "]" }
            / expected!("the end of a list indicated by ']'")

        rule list_items() -> Vec<String>
            = list_start()
            items:quoted_string() ** ","
            whitespace()* ","? whitespace()*
            list_end() {
                items
            }

        rule items() -> Vec<String>
            = whitespace()*
            items:(tuple_items() / list_items())
            whitespace()* { items }

        rule list_edit() -> ListEdit<String>
            = whitespace()* action:action() items:items() whitespace()* {
                ListEdit { action, items }
            }

        rule list_edits() -> Vec<ListEdit<String>>
            = e:list_edit() ** "," ","? { e }

        rule list_replace() -> Vec<ListEdit<String>>
            = items:items() {
                vec![ListEdit { action: ListEditAction::Replace, items }]
            }

        rule implicit_add() -> Vec<ListEdit<String>>
            // If the value is not prefixed with any of the syntax that we recognize as indicating
            // our list edit syntax, then it is implicitly an Add.
            = !(whitespace() / (action() list_start()) / (action() tuple_start()) / tuple_start() / list_start()) item:string() {
                vec![ListEdit { action: ListEditAction::Add, items: vec![item.to_owned()] }]
            }

        pub(crate) rule string_list_edits() -> Vec<ListEdit<String>>
            = implicit_add() / list_replace() / list_edits()
    }
}

mod err {
    #[derive(Debug, Eq, PartialEq)]
    pub(crate) struct ParseError {
        template: String,
    }

    impl ParseError {
        pub(super) fn new<S: AsRef<str>>(template: S) -> ParseError {
            let template_ref = template.as_ref();
            assert!(
                template_ref.contains("{name}"),
                "\
        Expected the template to contain at least one `{{name}}` placeholder, but found none: \
        {template_ref}.\
        "
            );
            ParseError {
                template: template_ref.to_owned(),
            }
        }

        pub(crate) fn render<S: AsRef<str>>(&self, name: S) -> String {
            self.template.replace("{name}", name.as_ref())
        }
    }
}

pub(crate) use err::ParseError;

fn format_parse_error(
    type_id: &str,
    value: &str,
    parse_error: peg::error::ParseError<peg::str::LineCol>,
) -> ParseError {
    let value_with_marker = value
        .split('\n')
        .enumerate()
        .map(|(index, line)| (index + 1, line))
        .map(|(line_no, line)| {
            if line_no == parse_error.location.line {
                format!(
                    "{}:{}\n  {}^",
                    line_no,
                    line,
                    "-".repeat(parse_error.location.column - 1)
                )
            } else {
                format!("{line_no}:{line}")
            }
        })
        .collect::<Vec<_>>()
        .join("\n");

    let mut choices = parse_error.expected.tokens().collect::<Vec<_>>();
    // N.B.: It appears to be the case that the peg parser parses alternatives concurrently and so
    // the ordering of choices is observed to be unstable. As such sort them for consistent error
    // messages.
    choices.sort_unstable();

    ParseError::new(format!(
        "\
    Problem parsing {{name}} {type_id} value:\n{value_with_marker}\nExpected {choices} at \
    line {line} column {column}\
    ",
        type_id = type_id,
        value_with_marker = value_with_marker,
        choices = render_choice(choices.as_slice()).unwrap_or_else(|| "nothing".to_owned()),
        line = parse_error.location.line,
        column = parse_error.location.column,
    ))
}

pub(crate) fn parse_string_list(value: &str) -> Result<Vec<ListEdit<String>>, ParseError> {
    option_value_parser::string_list_edits(value)
        .map_err(|e| format_parse_error("string list", value, e))
}

pub(crate) fn parse_bool(value: &str) -> Result<bool, ParseError> {
    match value.to_lowercase().as_str() {
        "true" => Ok(true),
        "false" => Ok(false),
        _ => Err(ParseError::new(format!(
            "Got '{value}' for {{name}}. Expected 'true' or 'false'."
        ))),
    }
}
