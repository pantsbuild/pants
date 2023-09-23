// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;
use std::env;

use super::id::{NameTransform, OptionId, Scope};
use super::OptionsSource;
use crate::parse::{parse_bool, parse_string_list};
use crate::ListEdit;

#[derive(Debug)]
pub struct Env {
  pub(crate) env: HashMap<String, String>,
}

impl Env {
  pub fn new(env: HashMap<String, String>) -> Self {
    Self { env }
  }

  pub fn capture_lossy() -> Self {
    Self::new(
      env::vars_os()
        .map(|(k, v)| {
          (
            k.to_string_lossy().to_string(),
            v.to_string_lossy().to_string(),
          )
        })
        .collect::<HashMap<_, _>>(),
    )
  }

  fn env_var_names(id: &OptionId) -> Vec<String> {
    let name = id.name("_", NameTransform::ToUpper);
    let mut names = vec![format!(
      "PANTS_{}_{}",
      id.0.name().replace('-', "_").to_ascii_uppercase(),
      name
    )];
    if id.0 == Scope::Global {
      names.push(format!("PANTS_{name}"));
    }
    if name.starts_with("PANTS_") {
      names.push(name);
    }
    names
  }
}

impl From<&Env> for Vec<(String, String)> {
  fn from(env: &Env) -> Self {
    env
      .env
      .iter()
      .map(|(k, v)| (k.clone(), v.clone()))
      .collect::<Vec<(_, _)>>()
  }
}

impl OptionsSource for Env {
  fn display(&self, id: &OptionId) -> String {
    Self::env_var_names(id).pop().unwrap()
  }

  fn get_string(&self, id: &OptionId) -> Result<Option<String>, String> {
    let env_var_names = Self::env_var_names(id);
    for env_var_name in &env_var_names {
      if let Some(value) = self.env.get(env_var_name) {
        return Ok(Some(value.to_owned()));
      }
    }
    Ok(None)
  }

  fn get_bool(&self, id: &OptionId) -> Result<Option<bool>, String> {
    if let Some(value) = self.get_string(id)? {
      parse_bool(&value)
        .map(Some)
        .map_err(|e| e.render(self.display(id)))
    } else {
      Ok(None)
    }
  }

  fn get_string_list(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<String>>>, String> {
    if let Some(value) = self.get_string(id)? {
      parse_string_list(&value)
        .map(Some)
        .map_err(|e| e.render(self.display(id)))
    } else {
      Ok(None)
    }
  }
}
