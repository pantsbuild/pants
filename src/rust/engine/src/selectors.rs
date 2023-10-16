// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::fmt;

use deepsize::DeepSizeOf;

use crate::python::TypeId;

#[derive(Clone, Copy, Debug, DeepSizeOf, Eq, Ord, PartialOrd, Hash, PartialEq)]
pub struct Get {
    pub output: TypeId,
    pub input: TypeId,
}

impl fmt::Display for Get {
    fn fmt(&self, f: &mut fmt::Formatter) -> Result<(), fmt::Error> {
        write!(f, "Get({}, {})", self.output, self.input)
    }
}

#[derive(Clone, Copy, DeepSizeOf, Eq, Ord, PartialOrd, Hash, PartialEq)]
pub struct Select {
    pub product: TypeId,
}

impl Select {
    pub fn new(product: TypeId) -> Select {
        Select { product }
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
#[derive(Clone, Copy, Debug, Hash, Ord, PartialOrd, Eq, PartialEq)]
pub enum DependencyKey {
    // A Get for a particular output/input pair.
    JustGet(Get),
    // A bare select with no projection.
    JustSelect(Select),
}

impl rule_graph::DependencyKey for DependencyKey {
    type TypeId = TypeId;

    ///
    /// Generates a DependencyKey for a "root" dependency.
    ///
    /// TODO: Currently this uses 'Select', but when https://github.com/pantsbuild/pants/issues/7490
    /// is implemented, it should probably use `Get`.
    ///
    fn new_root(product: TypeId) -> DependencyKey {
        DependencyKey::JustSelect(Select::new(product))
    }

    fn product(&self) -> TypeId {
        match self {
            DependencyKey::JustGet(ref g) => g.output,
            DependencyKey::JustSelect(ref s) => s.product,
        }
    }

    fn provided_param(&self) -> Option<TypeId> {
        match self {
            DependencyKey::JustGet(ref g) => Some(g.input),
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
