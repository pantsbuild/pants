// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use super::{DictEdit, DictEditAction, ListEdit, ListEditAction, Val};
use crate::render_choice;

use serde::de::{Deserialize, DeserializeOwned};
use std::collections::HashMap;
use std::fmt::Display;
use std::path::{Path, PathBuf};
use std::{fs, io};

peg::parser! {
    grammar option_value_parser() for str {
        use peg::ParseLiteral;

        rule whitespace() -> ()
            = quiet!{ " " / "\n" / "\r" / "\t" }

        rule value_with_ws<T>(parse_value: rule<T>) -> T
            = whitespace()* value:parse_value() whitespace()* { value }

        rule false() -> bool
            = quiet!{ ("F"/"f") ("A"/"a") ("L"/"l") ("S"/"s") ("E"/"e") } { false }

        rule true() -> bool
            = quiet!{ ("T"/"t") ("R"/"r") ("U"/"u") ("E"/"e") } { true }

        pub(crate) rule bool() -> bool
            = b:(true() / false() / expected!("'true' or 'false'")) { b }

        // Python numeric literals can include digit-separator underscores. It's unlikely
        // that anyone relies on those in option values, but since the old Python options
        // system accepted them, we support them here.
        rule digitpart() -> &'input str
            = dp:$(['0'..='9'] ("_"? ['0'..='9'])*) { dp }

        pub(crate) rule int() -> i64
            = i:$(("+" / "-")?digitpart()) { i.replace('_', "").parse::<i64>().unwrap() }

        pub(crate) rule float() -> f64
            = f:$(("+" / "-")?digitpart() "." digitpart()? (("e" / "E") ("+" / "-") digitpart())?) {
            f.replace('_', "").parse::<f64>().unwrap()
        }

        rule unquoted_string() -> String
            = s:(non_escaped_character() / escaped_character())+ { s.into_iter().collect() }

        rule non_escaped_character() -> char
            = !"\\" c:$([_]) { c.chars().next().unwrap() }

        pub(crate) rule quoted_string() -> String
            = string:(double_quoted_string() / single_quoted_string()) { string }

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

        // NB: ##method(X) is an undocumented peg feature expression that calls input.method(pos, X)
        // (see https://github.com/kevinmehall/rust-peg/issues/283).
        rule quoted_character(quote_char: &'static str) -> char
            = !(##parse_string_literal(quote_char) / "\\") c:$([_]) { c.chars().next().unwrap() }

        rule escaped_character() -> char
            = "\\" c:$([_]) { c.chars().next().unwrap() }

        rule list_add() -> ListEditAction
            = "+" { ListEditAction::Add }

        rule list_remove() -> ListEditAction
            = "-" { ListEditAction::Remove }

        rule list_action() -> ListEditAction
            = quiet!{ action:(list_add() / list_remove()) { action } }
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

        rule tuple_items<T>(parse_value: rule<T>) -> Vec<T>
            = tuple_start()
            items:value_with_ws(&parse_value) ** ","
            ","? whitespace()*
            tuple_end() {
                items
            }

        rule list_start() -> ()
            = quiet!{ "[" }
            / expected!("the start of a list indicated by '['")

        rule list_end() -> ()
            = quiet!{ "]" }
            / expected!("the end of a list indicated by ']'")

        rule list_items<T>(parse_value: rule<T>) -> Vec<T>
            = list_start()
            items:value_with_ws(&parse_value) ** ","
            ","? whitespace()*
            list_end() {
                items
            }

        rule items<T>(parse_value: rule<T>) -> Vec<T>
            = whitespace()*
            items:(tuple_items(&parse_value) / list_items(&parse_value))
            whitespace()* { items }

        rule list_edit<T>(parse_value: rule<T>) -> ListEdit<T>
            = whitespace()* action:list_action() items:items(&parse_value) whitespace()* {
                ListEdit { action, items }
            }

        rule list_edits<T>(parse_value: rule<T>) -> Vec<ListEdit<T>>
            = e:list_edit(&parse_value) ** "," ","? { e }

        rule list_replace<T>(parse_value: rule<T>) -> Vec<ListEdit<T>>
            = items:items(&parse_value) {
                vec![ListEdit { action: ListEditAction::Replace, items }]
            }

        rule implicit_add<T>(parse_raw_value: rule<T>) -> Vec<ListEdit<T>>
            // If the value is not prefixed with any of the syntax that we recognize as indicating
            // our list edit syntax, then it is implicitly an Add.
            = !(whitespace() / (list_action() list_start()) / (list_action() tuple_start()) /
                tuple_start() / list_start()
               ) item:parse_raw_value() {
                vec![ListEdit { action: ListEditAction::Add, items: vec![item] }]
            }

        rule scalar_list_edits<T>(parse_scalar: rule<T>) -> Vec<ListEdit<T>>
            = implicit_add(&parse_scalar) / list_replace(&parse_scalar) / list_edits(&parse_scalar)

        pub(crate) rule bool_list_edits() -> Vec<ListEdit<bool>> = scalar_list_edits(<bool()>)

        pub(crate) rule int_list_edits() -> Vec<ListEdit<i64>> = scalar_list_edits(<int()>)

        pub(crate) rule float_list_edits() -> Vec<ListEdit<f64>> = scalar_list_edits(<float()>)

        pub(crate) rule string_list_edits() -> Vec<ListEdit<String>>
            = implicit_add(<unquoted_string()>) / list_replace(<quoted_string()>) / list_edits(<quoted_string()>)

        // Heterogeneous values embedded in dicts. Note that float_val() must precede int_val() so that
        // the integer prefix of a float is not interpreted as an int.
        rule val() -> Val
            = v:(bool_val() / float_val() / int_val() / string_val() / list_val() / tuple_val() / dict_val()) {
            v
        }

        rule bool_val() -> Val = x:bool() { Val::Bool(x) }
        rule float_val() -> Val = x:float() { Val::Float(x) }
        rule int_val() -> Val = x:int() { Val::Int(x) }
        rule string_val() -> Val = x:quoted_string() { Val::String(x) }
        rule list_val() -> Val = items:list_items(<val()>) { Val::List(items) }
        rule tuple_val() -> Val = items:tuple_items(<val()>) { Val::List(items) }
        rule dict_val() -> Val = whitespace()* d:dict() { Val::Dict(d) }

        rule dict() -> HashMap<String, Val>
            = dict_start()
            items:dict_item() ** ","
            whitespace()* ","? whitespace()*
            dict_end()
            whitespace()* {
                items.into_iter().collect()
            }

        rule dict_start() -> ()
            = quiet!{ "{" }
            / expected!("the start of a dict indicated by '{' or '+{'")

        rule dict_end() -> ()
            = quiet!{ "}" }
            / expected!("the end of a dict indicated by '}'")

        rule dict_item() -> (String, Val)
            = whitespace()* key:quoted_string() whitespace()* ":" whitespace()* value:val() whitespace()* {
                (key, value)
            }

        pub(crate) rule dict_edit() -> DictEdit
            = whitespace()* plus:"+"? d:dict() {
                DictEdit {
                    action: if plus.is_some() { DictEditAction::Add } else { DictEditAction::Replace },
                    items: d,
                }
            }
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

pub(crate) fn parse_dict(value: &str) -> Result<DictEdit, ParseError> {
    option_value_parser::dict_edit(value).map_err(|e| format_parse_error("dict", value, e))
}

pub(crate) trait Parseable: Sized + DeserializeOwned {
    fn parse(value: &str) -> Result<Self, ParseError>;
    fn parse_list(value: &str) -> Result<Vec<ListEdit<Self>>, ParseError>;
}

impl Parseable for bool {
    fn parse(value: &str) -> Result<bool, ParseError> {
        option_value_parser::bool(value).map_err(|e| format_parse_error("bool", value, e))
    }

    fn parse_list(value: &str) -> Result<Vec<ListEdit<bool>>, ParseError> {
        option_value_parser::bool_list_edits(value)
            .map_err(|e| format_parse_error("bool list", value, e))
    }
}

impl Parseable for i64 {
    fn parse(value: &str) -> Result<i64, ParseError> {
        option_value_parser::int(value).map_err(|e| format_parse_error("int", value, e))
    }

    fn parse_list(value: &str) -> Result<Vec<ListEdit<i64>>, ParseError> {
        option_value_parser::int_list_edits(value)
            .map_err(|e| format_parse_error("int list", value, e))
    }
}

impl Parseable for f64 {
    fn parse(value: &str) -> Result<f64, ParseError> {
        option_value_parser::float(value).map_err(|e| format_parse_error("float", value, e))
    }

    fn parse_list(value: &str) -> Result<Vec<ListEdit<f64>>, ParseError> {
        option_value_parser::float_list_edits(value)
            .map_err(|e| format_parse_error("float list", value, e))
    }
}

impl Parseable for String {
    fn parse(value: &str) -> Result<String, ParseError> {
        Ok(value.to_owned())
    }

    fn parse_list(value: &str) -> Result<Vec<ListEdit<String>>, ParseError> {
        option_value_parser::string_list_edits(value)
            .map_err(|e| format_parse_error("string list", value, e))
    }
}

// If the corresponding unexpanded value points to a @fromfile, then the
// first component is the path to that file, and the second is the value from the file,
// or None if the file doesn't exist and the @?fromfile syntax was used.
//
// Otherwise, the first component is None and the second is the original value.
type ExpandedValue = (Option<PathBuf>, Option<String>);

// fn mk_parse_err(err: impl Display, path_opt: Option<Path>) -> ParseError {
//     let error_src = if let Some(path) = path_opt { format!("reading {path}") } else { "parsing value" };
//     ParseError::new(format!("Problem {error_src} for {{name}}: {err}"))
// }

fn mk_parse_err(err: impl Display, path: &Path) -> ParseError {
    ParseError::new(format!(
        "Problem reading {path} for {{name}}: {err}",
        path = path.display()
    ))
}

fn maybe_expand(value: String) -> Result<ExpandedValue, ParseError> {
    if let Some(suffix) = value.strip_prefix('@') {
        if suffix.starts_with('@') {
            // @@ escapes the initial @.
            Ok((None, Some(suffix.to_owned())))
        } else {
            match suffix.strip_prefix('?') {
                Some(subsuffix) => {
                    // @? means the path is allowed to not exist.
                    let path = PathBuf::from(subsuffix);
                    match fs::read_to_string(&path) {
                        Ok(content) => Ok((Some(path), Some(content))),
                        Err(err) if err.kind() == io::ErrorKind::NotFound => Ok((Some(path), None)),
                        Err(err) => Err(mk_parse_err(err, &path)),
                    }
                }
                _ => {
                    let path = PathBuf::from(suffix);
                    let content = fs::read_to_string(&path).map_err(|e| mk_parse_err(e, &path))?;
                    Ok((Some(path), Some(content)))
                }
            }
        }
    } else {
        Ok((None, Some(value)))
    }
}

pub(crate) fn expand(value: String) -> Result<Option<String>, ParseError> {
    let (_, expanded_value) = maybe_expand(value)?;
    Ok(expanded_value)
}

#[derive(Debug)]
enum FromfileType {
    Json,
    Yaml,
    Unknown,
}

impl FromfileType {
    fn detect(path: &Path) -> FromfileType {
        if let Some(ext) = path.extension() {
            if ext == "json" {
                return FromfileType::Json;
            } else if ext == "yml" || ext == "yaml" {
                return FromfileType::Yaml;
            };
        }
        FromfileType::Unknown
    }
}

fn try_deserialize<'a, DE: Deserialize<'a>>(
    value: &'a str,
    path_opt: Option<PathBuf>,
) -> Result<Option<DE>, ParseError> {
    if let Some(path) = path_opt {
        match FromfileType::detect(&path) {
            FromfileType::Json => serde_json::from_str(value).map_err(|e| mk_parse_err(e, &path)),
            FromfileType::Yaml => serde_yaml::from_str(value).map_err(|e| mk_parse_err(e, &path)),
            _ => Ok(None),
        }
    } else {
        Ok(None)
    }
}

pub(crate) fn expand_to_list<T: Parseable>(
    value: String,
) -> Result<Option<Vec<ListEdit<T>>>, ParseError> {
    let (path_opt, value_opt) = maybe_expand(value)?;
    if let Some(value) = value_opt {
        if let Some(items) = try_deserialize(&value, path_opt)? {
            Ok(Some(vec![ListEdit {
                action: ListEditAction::Replace,
                items,
            }]))
        } else {
            T::parse_list(&value).map(Some)
        }
    } else {
        Ok(None)
    }
}

pub(crate) fn expand_to_dict(value: String) -> Result<Option<DictEdit>, ParseError> {
    let (path_opt, value_opt) = maybe_expand(value)?;
    if let Some(value) = value_opt {
        if let Some(items) = try_deserialize(&value, path_opt)? {
            Ok(Some(DictEdit {
                action: DictEditAction::Replace,
                items,
            }))
        } else {
            parse_dict(&value).map(Some)
        }
    } else {
        Ok(None)
    }
}

#[cfg(test)]
pub(crate) mod test_util {
    use std::fs::File;
    use std::io::Write;
    use std::path::PathBuf;
    use tempfile::{tempdir, TempDir};

    pub(crate) fn write_fromfile(filename: &str, content: &str) -> (TempDir, PathBuf) {
        let tmpdir = tempdir().unwrap();
        let fromfile_path = tmpdir.path().join(filename);
        let mut fromfile = File::create(&fromfile_path).unwrap();
        fromfile.write_all(content.as_bytes()).unwrap();
        fromfile.flush().unwrap();
        (tmpdir, fromfile_path)
    }
}
