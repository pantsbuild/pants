// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::env;

use super::id::{NameTransform, OptionId, Scope};
use super::{DictEdit, OptionsSource};
use crate::parse::{expand, expand_to_dict, expand_to_list, Parseable};
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

    fn get_list<T: Parseable>(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<T>>>, String> {
        let arg_names = Self::arg_names(id, Negate::False);
        let mut edits = vec![];
        for arg in &self.args {
            let mut components = arg.as_str().splitn(2, '=');
            if let Some(name) = components.next() {
                if arg_names.contains_key(name) {
                    let value = components.next().ok_or_else(|| {
                        format!("Expected string list option {name} to have a value.")
                    })?;
                    if let Some(es) =
                        expand_to_list::<T>(value.to_string()).map_err(|e| e.render(name))?
                    {
                        edits.extend(es);
                    }
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
        match self.find_flag(Self::arg_names(id, Negate::False))? {
            Some((name, value, _)) => expand(value).map_err(|e| e.render(name)),
            _ => Ok(None),
        }
    }

    fn get_bool(&self, id: &OptionId) -> Result<Option<bool>, String> {
        let arg_names = Self::arg_names(id, Negate::True);
        match self.find_flag(arg_names)? {
            Some((_, s, negated)) if s.as_str() == "" => Ok(Some(!negated)),
            Some((name, value, negated)) => match expand(value).map_err(|e| e.render(&name))? {
                Some(value) => bool::parse(&value)
                    .map(|b| Some(b ^ negated))
                    .map_err(|e| e.render(&name)),
                _ => Ok(None),
            },
            _ => Ok(None),
        }
    }

    fn get_bool_list(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<bool>>>, String> {
        self.get_list::<bool>(id)
    }

    fn get_int_list(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<i64>>>, String> {
        self.get_list::<i64>(id)
    }

    fn get_float_list(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<f64>>>, String> {
        self.get_list::<f64>(id)
    }

    fn get_string_list(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<String>>>, String> {
        self.get_list::<String>(id)
    }

    fn get_dict(&self, id: &OptionId) -> Result<Option<DictEdit>, String> {
        match self.find_flag(Self::arg_names(id, Negate::False))? {
            Some((name, value, _)) => expand_to_dict(value).map_err(|e| e.render(name)),
            None => Ok(None),
        }
    }
}
