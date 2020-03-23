// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(unused_must_use)]

#[macro_use]
extern crate prost_derive;

mod gen;
pub use crate::gen::*;

mod gen_for_tower;
pub use crate::gen_for_tower::*;

mod conversions;
#[cfg(test)]
mod conversions_tests;

mod metadata;
pub use metadata::call_option;

mod verification;
pub use crate::verification::verify_directory_canonical;
#[cfg(test)]
mod verification_tests;
