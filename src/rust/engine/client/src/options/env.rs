// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;
use std::env;

use super::id::{NameTransform, OptionId, Scope};
use super::OptionsSource;

#[derive(Debug)]
pub(crate) struct Env {
  env: HashMap<String, String>,
}

impl Env {
  pub(crate) fn capture() -> Env {
    Env {
      env: env::vars().collect::<HashMap<_, _>>(),
    }
  }

  fn env_var_names(id: &OptionId) -> Vec<String> {
    let name = id.name("_", NameTransform::ToUpper);
    let mut names = vec![format!(
      "PANTS_{}_{}",
      id.0.name().to_ascii_uppercase(),
      name
    )];
    if id.0 == Scope::GLOBAL {
      names.push(format!("PANTS_{}", name));
    }
    if name.starts_with("PANTS_") {
      names.push(name);
    }
    names
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
}
