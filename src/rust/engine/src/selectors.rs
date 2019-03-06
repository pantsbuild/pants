// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::core::TypeId;
use std::fmt;

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct Get {
  pub product: TypeId,
  pub subject: TypeId,
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
