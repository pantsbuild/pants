// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::env;

use super::id::{NameTransform, OptionId, Scope};
use super::parse::{
    parse_bool, parse_bool_list, parse_dict, parse_float_list, parse_int_list, ParseError,
};
use super::{DictEdit, OptionsSource};
use crate::parse::parse_string_list;
use crate::ListEdit;
use std::collections::HashMap;

pub struct Args {
    pub(crate) args: Vec<String>,
}

#[derive(PartialEq)]
enum Negate {
    True,
    False,
}

impl Args {
    pub fn new(args: Vec<String>) -> Self {
        Self { args }
    }

    pub fn argv() -> Self {
        Self::new(env::args().collect::<Vec<_>>())
    }

    fn arg_name(id: &OptionId, negate: Negate) -> String {
        format!(
            "--{}{}{}",
            match negate {
                Negate::False => "",
                Negate::True => "no-",
            },
            match &id.0 {
                Scope::Global => "".to_string(),
                Scope::Scope(scope) => format!("{}-", scope.to_ascii_lowercase()),
            },
            id.name("-", NameTransform::ToLower)
        )
    }

    fn arg_names(id: &OptionId, negate: Negate) -> HashMap<String, bool> {
        let mut arg_names = HashMap::new();
        if let Some(switch) = id.2 {
            arg_names.insert(format!("-{switch}"), false);
            if negate == Negate::True {
                arg_names.insert(format!("--no-{switch}"), true);
            }
        }
        arg_names.insert(Self::arg_name(id, Negate::False), false);
        if negate == Negate::True {
            arg_names.insert(Self::arg_name(id, Negate::True), true);
        }
        arg_names
    }

    fn find_flag(
        &self,
        flag_names: HashMap<String, bool>,
    ) -> Result<Option<(String, String, bool)>, String> {
        for arg in self.args.iter().rev() {
            let mut components = arg.as_str().splitn(2, '=');
            if let Some(name) = components.next() {
                if let Some(negated) = flag_names.get(name) {
                    return Ok(Some((
                        name.to_owned(),
                        components.next().unwrap_or("").to_owned(),
                        *negated,
                    )));
                }
            }
        }
        Ok(None)
    }

    fn get_list<T>(
        &self,
        id: &OptionId,
        parse_list: fn(&str) -> Result<Vec<ListEdit<T>>, ParseError>,
    ) -> Result<Option<Vec<ListEdit<T>>>, String> {
        let arg_names = Self::arg_names(id, Negate::False);
        let mut edits = vec![];
        for arg in &self.args {
            let mut components = arg.as_str().splitn(2, '=');
            if let Some(name) = components.next() {
                if arg_names.contains_key(name) {
                    let value = components.next().ok_or_else(|| {
                        format!("Expected string list option {name} to have a value.")
                    })?;
                    edits.extend(parse_list(value).map_err(|e| e.render(name))?)
                }
            }
        }
        if edits.is_empty() {
            Ok(None)
        } else {
            Ok(Some(edits))
        }
    }
}

impl OptionsSource for Args {
    fn display(&self, id: &OptionId) -> String {
        Self::arg_name(id, Negate::False)
    }

    fn get_string(&self, id: &OptionId) -> Result<Option<String>, String> {
        self.find_flag(Self::arg_names(id, Negate::False))
            .map(|value| value.map(|(_, v, _)| v))
    }

    fn get_bool(&self, id: &OptionId) -> Result<Option<bool>, String> {
        let arg_names = Self::arg_names(id, Negate::True);
        match self.find_flag(arg_names)? {
            Some((_, s, negated)) if s.as_str() == "" => Ok(Some(!negated)),
            Some((name, ref value, negated)) => parse_bool(value)
                .map(|b| Some(b ^ negated))
                .map_err(|e| e.render(name)),
            None => Ok(None),
        }
    }

    fn get_bool_list(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<bool>>>, String> {
        self.get_list(id, parse_bool_list)
    }

    fn get_int_list(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<i64>>>, String> {
        self.get_list(id, parse_int_list)
    }

    fn get_float_list(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<f64>>>, String> {
        self.get_list(id, parse_float_list)
    }

    fn get_string_list(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<String>>>, String> {
        self.get_list(id, parse_string_list)
    }

    fn get_dict(&self, id: &OptionId) -> Result<Option<DictEdit>, String> {
        match self.find_flag(Self::arg_names(id, Negate::False))? {
            Some((name, ref value, _)) => parse_dict(value)
                .map(|e| Some(e))
                .map_err(|e| e.render(name)),
            None => Ok(None),
        }
    }
}
