// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::env;

use super::id::{NameTransform, OptionId, Scope};
use super::parse::parse_bool;
use super::OptionsSource;
use crate::parse::parse_string_list;
use crate::ListEdit;
use std::collections::HashMap;

pub(crate) struct Args {
    pub(crate) args: Vec<String>,
}

#[derive(PartialEq)]
enum Negate {
    True,
    False,
}

impl Args {
    pub(crate) fn argv() -> Args {
        Args {
            args: env::args().collect::<Vec<_>>(),
        }
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
            arg_names.insert(format!("-{}", switch), false);
            if negate == Negate::True {
                arg_names.insert(format!("--no-{}", switch), true);
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

    fn get_string_list(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<String>>>, String> {
        let arg_names = Self::arg_names(id, Negate::False);
        let mut edits = vec![];
        for arg in &self.args {
            let mut components = arg.as_str().splitn(2, '=');
            if let Some(name) = components.next() {
                if arg_names.contains_key(name) {
                    let value = components.next().ok_or_else(|| {
                        format!(
                            "Expected string list option {name} to have a value.",
                            name = name
                        )
                    })?;
                    edits.extend(parse_string_list(value).map_err(|e| e.render(name))?)
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
