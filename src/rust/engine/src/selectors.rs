// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::core::{TypeConstraint, TypeId};
use crate::externs;
use std::fmt;

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct Get {
  pub product: TypeConstraint,
  pub subject: TypeId,
}

#[derive(Clone, Eq, Hash, PartialEq)]
pub struct Select {
  pub product: TypeConstraint,
}

impl Select {
  pub fn new(product: TypeConstraint) -> Select {
    Select { product: product }
  }
}

impl fmt::Debug for Select {
  fn fmt(&self, f: &mut fmt::Formatter) -> Result<(), fmt::Error> {
    write!(
      f,
      "Select {{ product: {} }}",
      externs::key_to_str(&self.product.0)
    )
  }
}
