// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use pyo3::create_exception;
use pyo3::exceptions::PyException;
use pyo3::prelude::*;

use address::parse_address;

create_exception!(native_engine, AddressParseException, PyException);

pub fn register(py: Python, m: &PyModule) -> PyResult<()> {
  m.add(
    "AddressParseException",
    py.get_type::<AddressParseException>(),
  )?;
  m.add_function(wrap_pyfunction!(address_parse, m)?)?;
  Ok(())
}

/// Parses an Address spec into:
/// 1. a path component
/// 2. a target component
/// 3. a generated component
///
#[pyfunction]
fn address_parse(spec: &str) -> PyResult<(&str, Option<&str>, Option<&str>)> {
  let address = parse_address(spec).map_err(AddressParseException::new_err)?;
  Ok((address.path, address.target, address.generated))
}
