// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::env;

use super::id::{NameTransform, OptionId, Scope};
use super::parse::parse_bool;
use super::OptionsSource;
use crate::options::parse::parse_string_list;
use crate::options::ListEdit;

pub(crate) struct Args {
  args: Vec<String>,
}

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

  fn find_string(&self, arg_name: &str) -> Result<Option<String>, String> {
    for arg in self.args.iter().rev() {
      let mut components = arg.as_str().splitn(2, '=');
      if let Some(name) = components.next() {
        if name == arg_name {
          return Ok(Some(components.next().unwrap_or("").to_owned()));
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
    if let Some(switch) = id.2 {
      let prefixes = [format!("-{}=", switch), format!("-{}", switch)];
      for arg in self.args.iter().rev() {
        for prefix in &prefixes {
          if arg.starts_with(&*prefix) {
            return Ok(Some(arg[prefix.len()..].to_owned()));
          }
        }
      }
    }
    self.find_string(&Self::arg_name(id, Negate::False))
  }

  fn get_bool(&self, id: &OptionId) -> Result<Option<bool>, String> {
    let arg_name = Self::arg_name(id, Negate::False);
    match self.find_string(&arg_name)? {
      Some(s) if s.as_str() == "" => Ok(Some(true)),
      Some(ref value) => parse_bool(&arg_name, value).map(Some),
      None => {
        let no_arg_name = Self::arg_name(id, Negate::True);
        match self.find_string(&no_arg_name)? {
          Some(s) if s.as_str() == "" => Ok(Some(false)),
          Some(ref value) => parse_bool(&no_arg_name, value)
            .map(|value| !value)
            .map(Some),
          None => Ok(None),
        }
      }
    }
  }

  fn get_string_list(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<String>>>, String> {
    let arg_name = Self::arg_name(id, Negate::False);
    let mut edits = vec![];
    for arg in &self.args {
      let mut components = arg.as_str().splitn(2, '=');
      if let Some(name) = components.next() {
        if name == arg_name {
          let value = components.next().ok_or_else(|| {
            format!(
              "Expected string list option {name} to have a value.",
              name = name
            )
          })?;
          edits.extend(parse_string_list(name, value)?)
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
