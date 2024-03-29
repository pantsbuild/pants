// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::env;

use super::id::{is_valid_scope_name, NameTransform, OptionId, Scope};
use super::{DictEdit, OptionsSource};
use crate::parse::{expand, expand_to_dict, expand_to_list, ParseError, Parseable};
use crate::ListEdit;
use core::iter::once;
use itertools::{chain, Itertools};

#[derive(Debug)]
struct Arg {
    context: Scope,
    flag: String,
    value: Option<String>,
}

impl Arg {
    /// Checks if this arg's flag is equal to the provided strings concatenated with dashes.
    /// E.g., "--foo-bar" matches ["-", "foo", "bar"].
    fn _flag_match<'a>(&self, dash_separated_strs: impl Iterator<Item = &'a str>) -> bool {
        #[allow(unstable_name_collisions)]
        // intersperse is provided by itertools::Itertools, but is also in the Rust nightly
        // as an experimental feature of standard Iterator. If/when that becomes standard we
        // can use it, but for now we must squelch the name collision.
        itertools::equal(
            self.flag.chars(),
            dash_separated_strs
                .map(str::chars)
                .intersperse("-".chars())
                .flatten(),
        )
    }

    fn _prefix<'a>(negate: bool) -> impl Iterator<Item = &'a str> {
        if negate {
            once("--no")
        } else {
            once("-")
        }
    }

    // Check if --scope-flag matches.
    fn _matches_explicit_scope(&self, id: &OptionId, negate: bool) -> bool {
        self._flag_match(chain![
            Self::_prefix(negate),
            once(id.scope.name()),
            id.name_components_strs()
        ])
    }

    // Check if --flag matches in the context of the current goal's scope.
    fn _matches_implicit_scope(&self, id: &OptionId, negate: bool) -> bool {
        self.context == id.scope
            && self._flag_match(chain![Self::_prefix(negate), id.name_components_strs()])
    }

    // Check if -s matches for a short name s, if any.
    fn _matches_short(&self, id: &OptionId) -> bool {
        if let Some(sn) = &id.short_name {
            self._flag_match(chain![once(""), once(sn.as_ref())])
        } else {
            false
        }
    }

    /// Checks if this arg provides a value for the specified option, either negated or not.
    fn _matches(&self, id: &OptionId, negate: bool) -> bool {
        self._matches_explicit_scope(id, negate)
            || self._matches_implicit_scope(id, negate)
            || self._matches_short(id)
    }

    fn matches(&self, id: &OptionId) -> bool {
        self._matches(id, false)
    }

    fn matches_negation(&self, id: &OptionId) -> bool {
        self._matches(id, true)
    }

    fn to_bool(&self) -> Result<Option<bool>, ParseError> {
        // An arg can represent a bool either by having an explicit value parseable as a bool,
        // or by having no value (in which case it represents true).
        match &self.value {
            Some(value) => match expand(value.to_string())? {
                Some(s) => bool::parse(&s).map(Some),
                _ => Ok(None),
            },
            None => Ok(Some(true)),
        }
    }
}

#[derive(Debug)]
pub struct Args {
    args: Vec<Arg>,
}

impl Args {
    /// Create an Args instance with the provided args, which must *not* include the
    /// argv[0] process name.
    pub fn new<I: IntoIterator<Item = String>>(arg_strs: I) -> Self {
        let mut args: Vec<Arg> = vec![];
        let mut scope = Scope::Global;
        for arg_str in arg_strs.into_iter() {
            if arg_str.starts_with("--") {
                let mut components = arg_str.splitn(2, '=');
                let flag = components.next().unwrap();
                if flag.is_empty() {
                    // We've hit the passthrough args delimiter (`--`), so don't look further.
                    break;
                } else {
                    args.push(Arg {
                        context: scope.clone(),
                        flag: flag.to_string(),
                        value: components.next().map(str::to_string),
                    });
                }
            } else if arg_str.starts_with('-') && arg_str.len() >= 2 {
                let (flag, mut value) = arg_str.split_at(2);
                // We support -ldebug and -l=debug, so strip that extraneous equals sign.
                if let Some(stripped) = value.strip_prefix('=') {
                    value = stripped;
                }
                args.push(Arg {
                    context: scope.clone(),
                    flag: flag.to_string(),
                    value: if value.is_empty() {
                        None
                    } else {
                        Some(value.to_string())
                    },
                });
            } else if is_valid_scope_name(&arg_str) {
                scope = Scope::Scope(arg_str)
            }
        }

        Self { args }
    }

    pub fn argv() -> Self {
        let mut args = env::args().collect::<Vec<_>>().into_iter();
        args.next(); // Consume the process name (argv[0]).
        Self::new(env::args().collect::<Vec<_>>())
    }

    fn get_list<T: Parseable>(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<T>>>, String> {
        let mut edits = vec![];
        for arg in &self.args {
            if arg.matches(id) {
                let value = arg.value.as_ref().ok_or_else(|| {
                    format!("Expected list option {} to have a value.", self.display(id))
                })?;
                if let Some(es) =
                    expand_to_list::<T>(value.to_string()).map_err(|e| e.render(&arg.flag))?
                {
                    edits.extend(es);
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
        format!(
            "--{}{}",
            match &id.scope {
                Scope::Global => "".to_string(),
                Scope::Scope(scope) => format!("{}-", scope.to_ascii_lowercase()),
            },
            id.name("-", NameTransform::ToLower)
        )
    }

    fn get_string(&self, id: &OptionId) -> Result<Option<String>, String> {
        // We iterate in reverse so that the rightmost arg wins in case an option
        // is specified multiple times.
        for arg in self.args.iter().rev() {
            if arg.matches(id) {
                return expand(arg.value.clone().ok_or_else(|| {
                    format!("Expected list option {} to have a value.", self.display(id))
                })?)
                .map_err(|e| e.render(&arg.flag));
            };
        }
        Ok(None)
    }

    fn get_bool(&self, id: &OptionId) -> Result<Option<bool>, String> {
        // We iterate in reverse so that the rightmost arg wins in case an option
        // is specified multiple times.
        for arg in self.args.iter().rev() {
            if arg.matches(id) {
                return arg.to_bool().map_err(|e| e.render(&arg.flag));
            } else if arg.matches_negation(id) {
                return arg
                    .to_bool()
                    .map(|ob| ob.map(|b| b ^ true))
                    .map_err(|e| e.render(&arg.flag));
            }
        }
        Ok(None)
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
        // We iterate in reverse so that the rightmost arg wins in case an option
        // is specified multiple times.
        for arg in self.args.iter().rev() {
            if arg.matches(id) {
                return expand_to_dict(arg.value.clone().ok_or_else(|| {
                    format!("Expected list option {} to have a value.", self.display(id))
                })?)
                .map_err(|e| e.render(&arg.flag));
            }
        }
        Ok(None)
    }
}
