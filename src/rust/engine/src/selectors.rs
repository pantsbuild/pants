// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use core::{TypeConstraint, TypeId};

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct Get {
  pub product: TypeConstraint,
  pub subject: TypeId,
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub struct Select {
  pub product: TypeConstraint,
}

impl Select {
  pub fn new(product: TypeConstraint) -> Select {
    Select { product: product }
  }
}
