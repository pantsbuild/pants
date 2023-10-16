// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use pyo3::create_exception;
use pyo3::exceptions::PyException;
use pyo3::prelude::*;

create_exception!(native_engine, AddressParseException, PyException);

pub fn register(py: Python, m: &PyModule) -> PyResult<()> {
    m.add(
        "AddressParseException",
        py.get_type::<AddressParseException>(),
    )?;
    m.add_function(wrap_pyfunction!(address_spec_parse, m)?)?;
    Ok(())
}

/// 1. a path component
/// 2. a target component
/// 3. a generated component
/// 4. a sequence of key/value parameters
type ParsedAddress<'a> = (
    &'a str,
    Option<&'a str>,
    Option<&'a str>,
    Vec<(&'a str, &'a str)>,
);

/// 1. an address
/// 2. an optional wildcard component (`:` or `::`)
type ParsedSpec<'a> = (ParsedAddress<'a>, Option<&'a str>);

/// Parses an "address spec", which may come from the CLI or from a BUILD file.
///
/// The underlying parser will accept some combinations of syntax which may not (yet) be legal in
/// certain contexts. For example: a `!` ignore or `::` wildcard may be successfully parsed even
/// when other address syntax is used: if the combination of syntax is not legal in a particular
/// context, the caller should validate that.
///
/// TODO: If more of spec/address validation is ported to Rust, it might be worth defining a
/// pyclass for the return type.
#[pyfunction]
fn address_spec_parse(spec_str: &str) -> PyResult<ParsedSpec> {
    let spec = address::parse_address_spec(spec_str).map_err(AddressParseException::new_err)?;
    Ok((
        (
            spec.address.path,
            spec.address.target,
            spec.address.generated,
            spec.address.parameters,
        ),
        spec.wildcard,
    ))
}
