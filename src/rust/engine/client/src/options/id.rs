// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::fmt;
use std::fmt::{Display, Formatter};

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Scope {
  GLOBAL,
  Scope(String),
}

impl Scope {
  pub fn named(name: &str) -> Scope {
    match name {
      "GLOBAL" => Scope::GLOBAL,
      scope => Scope::Scope(scope.to_owned()),
    }
  }

  pub fn name(&self) -> &str {
    match self {
      Scope::GLOBAL => "GLOBAL",
      Scope::Scope(scope) => scope.as_str(),
    }
  }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OptionId(
  pub(crate) Scope,
  pub(crate) Vec<String>,
  pub(crate) Option<char>,
);

impl OptionId {
  pub fn new<Component, Name>(
    scope: Scope,
    name: Name,
    switch: Option<char>,
  ) -> Result<OptionId, String>
  where
    Component: AsRef<str>,
    Name: Iterator<Item = Component>,
  {
    let name_components = name
      .map(|component| component.as_ref().to_string())
      .collect::<Vec<_>>();
    if name_components.is_empty() {
      return Err(format!(
        "Cannot create an OptionId with en empty name. Given a scope of {:?}.",
        scope
      ));
    }
    Ok(OptionId(scope, name_components, switch))
  }
}

impl Display for OptionId {
  fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
    write!(
      f,
      "[{}] {}",
      self.scope(),
      self.name("_", NameTransform::None)
    )
  }
}

#[macro_export]
macro_rules! option_id {
    (-$switch:literal, [$scope:literal], $($name_component:literal),+) => {
        $crate::options::OptionId::new(
            $crate::options::Scope::named($scope),
            [$($name_component),+].iter(),
            Some($switch)
        ).expect("Creating an OptionId via macro should ensure at least one name component")
    };
    (-$switch:literal, $($name_component:literal),+) => {
        $crate::options::OptionId::new(
            $crate::options::Scope::GLOBAL,
            [$($name_component),+].iter(),
            Some($switch)
        ).expect("Creating an OptionId via macro should ensure at least one name component")
    };
    ([$scope:literal], $($name_component:literal),+) => {
        $crate::options::OptionId::new(
            $crate::options::Scope::named($scope),
            [$($name_component),+].iter(),
            None
        ).expect("Creating an OptionId via macro should ensure at least one name component")
    };
    ($($name_component:literal),+) => {
        $crate::options::OptionId::new(
            $crate::options::Scope::GLOBAL,
            [$($name_component),+].iter(),
            None
        ).expect("Creating an OptionId via macro should ensure at least one name component")
    };
}

pub(crate) enum NameTransform {
  None,
  ToLower,
  ToUpper,
}

impl OptionId {
  pub(crate) fn scope(&self) -> &str {
    self.0.name()
  }

  pub(crate) fn name(&self, sep: &str, transform: NameTransform) -> String {
    self
      .1
      .iter()
      .map(|component| match transform {
        NameTransform::None => component.to_owned(),
        NameTransform::ToLower => component.to_ascii_lowercase(),
        NameTransform::ToUpper => component.to_ascii_uppercase(),
      })
      .collect::<Vec<_>>()
      .join(sep)
  }
}

#[cfg(test)]
mod test {
  use crate::options::id::{OptionId, Scope};

  #[test]
  fn test_option_id_global_switch() {
    let option_id = option_id!(-'x', "bar", "baz");
    assert_eq!(
      OptionId::new(Scope::GLOBAL, ["bar", "baz"].iter(), Some('x')).unwrap(),
      option_id
    );
    assert_eq!("GLOBAL", option_id.scope());
  }

  #[test]
  fn test_option_id_global() {
    let option_id = option_id!("bar", "baz");
    assert_eq!(
      OptionId::new(Scope::GLOBAL, ["bar", "baz"].iter(), None).unwrap(),
      option_id
    );
    assert_eq!("GLOBAL", option_id.scope());
  }

  #[test]
  fn test_option_id_scope_switch() {
    let option_id = option_id!(-'f', ["foo-bar"], "baz", "spam");
    assert_eq!(
      OptionId::new(
        Scope::Scope("foo-bar".to_owned()),
        ["baz", "spam"].iter(),
        Some('f')
      )
      .unwrap(),
      option_id
    );
    assert_eq!("foo-bar", option_id.scope());
  }

  #[test]
  fn test_option_id_scope() {
    let option_id = option_id!(["foo-bar"], "baz", "spam");
    assert_eq!(
      OptionId::new(
        Scope::Scope("foo-bar".to_owned()),
        ["baz", "spam"].iter(),
        None
      )
      .unwrap(),
      option_id
    );
    assert_eq!("foo-bar", option_id.scope());
  }
}
