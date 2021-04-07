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
            = "+" { ListEditAction::ADD }

        rule remove() -> ListEditAction
            = "-" { ListEditAction::REMOVE }

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
            = tuple_start() items:string() ** "," ","? tuple_end() { items }

        rule list_start() -> ()
            = quiet!{ "[" }
            / expected!("the start of a list indicated by '['")

        rule list_end() -> ()
            = quiet!{ "]" }
            / expected!("the end of a list indicated by ']'")

        rule list_items() -> Vec<String>
            = list_start() items:string() ** "," ","? list_end() { items }

        rule items() -> Vec<String>
            = tuple_items()
            / list_items()

        rule list_edit() -> ListEdit<String>
            = whitespace()* action:action() items:items() whitespace()* {
                ListEdit { action, items }
            }

        rule list_edits() -> Vec<ListEdit<String>>
            = e:list_edit() ** "," ","? { e }

        rule list_replace() -> Vec<ListEdit<String>>
            = items:items() {
                vec![ListEdit { action: ListEditAction::REPLACE, items }]
            }

        rule implicit_add() -> Vec<ListEdit<String>>
            = !(whitespace() / add() / remove() / tuple_start() / list_start()) item:$([_]+) {
                vec![ListEdit { action: ListEditAction::ADD, items: vec![item.to_owned()] }]
            }

        pub(crate) rule string_list_edits() -> Vec<ListEdit<String>>
            = list_edits() / list_replace() / implicit_add()
    }
}

fn format_parse_error(
  id: &str,
  type_id: &str,
  value: &str,
  parse_error: peg::error::ParseError<peg::str::LineCol>,
) -> String {
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
        format!("{}:{}", line_no, line)
      }
    })
    .collect::<Vec<_>>()
    .join("\n");
  format!(
    "Problem parsing {} {} value:\n{}\nExpected {} at line {} column {}",
    id,
    type_id,
    value_with_marker,
    render_choice(parse_error.expected.tokens().collect::<Vec<_>>().as_slice())
      .unwrap_or_else(|| "nothing".to_owned()),
    parse_error.location.line,
    parse_error.location.column,
  )
}

pub(crate) fn parse_string_list(name: &str, value: &str) -> Result<Vec<ListEdit<String>>, String> {
  option_value_parser::string_list_edits(&value)
    .map_err(|e| format_parse_error(name, "string list", &*value, e))
}

pub(crate) fn parse_bool(name: &str, value: &str) -> Result<bool, String> {
  match value.to_lowercase().as_str() {
    "true" => Ok(true),
    "false" => Ok(false),
    _ => Err(format!(
      "Got '{}' for {}. Expected 'true' or 'false'.",
      value, name
    )),
  }
}
