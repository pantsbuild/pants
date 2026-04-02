// Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

mod field;
mod util;

use pyo3::prelude::*;

pub use field::{
    AsyncFieldMixin, BoolField, Field, ScalarField, SequenceField, StringField,
    StringSequenceField, TriBoolField,
};
pub use util::NoFieldValue;

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Field>()?;
    m.add_class::<ScalarField>()?;
    m.add_class::<BoolField>()?;
    m.add_class::<TriBoolField>()?;
    m.add_class::<StringField>()?;
    m.add_class::<SequenceField>()?;
    m.add_class::<StringSequenceField>()?;
    m.add_class::<AsyncFieldMixin>()?;
    m.add_class::<NoFieldValue>()?;

    m.add("NO_VALUE", NoFieldValue)?;

    Ok(())
}
