// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::core::TypeId;
use std::fmt;

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct Get {
  pub product: TypeId,
  pub subject: TypeId,
}

impl fmt::Display for Get {
  fn fmt(&self, f: &mut fmt::Formatter) -> Result<(), fmt::Error> {
    write!(f, "Get({}, {})", self.product, self.subject)
  }
}

#[derive(Clone, Eq, Hash, PartialEq)]
pub struct Select {
  pub product: TypeId,
}

impl Select {
  pub fn new(product: TypeId) -> Select {
    Select { product: product }
  }
}

impl fmt::Debug for Select {
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> Result<(), fmt::Error> {
    write!(f, "Select {{ product: {} }}", self.product,)
  }
}

///
/// A key for the dependencies used from a rule.
///
#[derive(Eq, Hash, PartialEq, Clone, Debug)]
pub enum DependencyKey {
  // A Get for a particular product/subject pair.
  JustGet(Get),
  // A bare select with no projection.
  JustSelect(Select),
}

impl DependencyKey {
  ///
  /// Generates a DependencyKey for a "root" dependency.
  ///
  /// TODO: Currently this uses 'Select', but when https://github.com/pantsbuild/pants/issues/7490
  /// is implemented, it should probably use `Get`.
  ///
  pub fn new_root(product: TypeId) -> DependencyKey {
    DependencyKey::JustSelect(Select::new(product))
  }

  ///
  /// Returns the product (output) type for this dependency.
  ///
  pub fn product(&self) -> TypeId {
    match self {
      DependencyKey::JustGet(ref g) => g.product,
      DependencyKey::JustSelect(ref s) => s.product,
    }
  }

  ///
  /// Returns the Param (input) type for this dependency, if it provides one.
  ///
  pub fn provided_param(&self) -> Option<TypeId> {
    match self {
      DependencyKey::JustGet(ref g) => Some(g.subject),
      DependencyKey::JustSelect(_) => None,
    }
  }
}

impl fmt::Display for DependencyKey {
  fn fmt(&self, f: &mut fmt::Formatter) -> Result<(), fmt::Error> {
    match self {
      DependencyKey::JustSelect(s) => write!(f, "{}", s.product),
      DependencyKey::JustGet(g) => write!(f, "{}", g),
    }
  }
}
