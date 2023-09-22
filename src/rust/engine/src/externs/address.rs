// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::borrow::Cow;
use std::collections::{BTreeMap, HashSet};
use std::ffi::OsStr;
use std::hash::{Hash, Hasher};
use std::path::{Path, PathBuf};

use pyo3::basic::CompareOp;
use pyo3::create_exception;
use pyo3::exceptions::{PyAssertionError, PyException};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyFrozenSet, PyType};

use fnv::FnvHasher;
use lazy_static::lazy_static;

create_exception!(native_engine, AddressParseException, PyException);
create_exception!(native_engine, InvalidAddressError, AddressParseException);
create_exception!(native_engine, InvalidSpecPathError, InvalidAddressError);
create_exception!(native_engine, InvalidTargetNameError, InvalidAddressError);
create_exception!(native_engine, InvalidParametersError, InvalidAddressError);
create_exception!(native_engine, UnsupportedWildcardError, InvalidAddressError);

pub fn register(py: Python, m: &PyModule) -> PyResult<()> {
  m.add_function(wrap_pyfunction!(address_spec_parse, m)?)?;

  m.add(
    "AddressParseException",
    py.get_type::<AddressParseException>(),
  )?;
  m.add("InvalidAddressError", py.get_type::<InvalidAddressError>())?;
  m.add(
    "InvalidSpecPathError",
    py.get_type::<InvalidSpecPathError>(),
  )?;
  m.add(
    "InvalidTargetNameError",
    py.get_type::<InvalidTargetNameError>(),
  )?;
  m.add(
    "InvalidParametersError",
    py.get_type::<InvalidParametersError>(),
  )?;
  m.add(
    "UnsupportedWildcardError",
    py.get_type::<UnsupportedWildcardError>(),
  )?;

  m.add_class::<AddressInput>()?;
  m.add_class::<Address>()?;

  m.add(
    "BANNED_CHARS_IN_TARGET_NAME",
    PyFrozenSet::new(py, BANNED_CHARS_IN_TARGET_NAME.iter())?,
  )?;
  m.add(
    "BANNED_CHARS_IN_GENERATED_NAME",
    PyFrozenSet::new(py, BANNED_CHARS_IN_GENERATED_NAME.iter())?,
  )?;
  m.add(
    "BANNED_CHARS_IN_PARAMETERS",
    PyFrozenSet::new(py, BANNED_CHARS_IN_PARAMETERS.iter())?,
  )?;

  Ok(())
}

lazy_static! {
  // `:`, `#`, `@` are used as delimiters already. Others are reserved for possible future needs.
  pub static ref BANNED_CHARS_IN_TARGET_NAME: HashSet<char> =
    [':', '#', '!', '@', '?', '/', '\\', '='].into();
  pub static ref BANNED_CHARS_IN_GENERATED_NAME: HashSet<char> =
    [':', '#', '!', '@', '?', '='].into();
  pub static ref BANNED_CHARS_IN_PARAMETERS: HashSet<char> =
    [':', '#', '!', '@', '?', '=', ',', ' '].into();
}

#[pyclass(name = "AddressInput", weakref)]
#[derive(Debug, Hash, Eq, PartialEq)]
pub struct AddressInput {
  original_spec: String,
  path_component: PathBuf,
  target_component: Option<String>,
  generated_component: Option<String>,
  parameters: BTreeMap<String, String>,
  description_of_origin: String,
}

#[pymethods]
impl AddressInput {
  #[new]
  fn __new__(
    original_spec: String,
    path_component: PathBuf,
    description_of_origin: String,
    target_component: Option<String>,
    generated_component: Option<String>,
    parameters: Option<BTreeMap<String, String>>,
  ) -> PyResult<Self> {
    if let Some(target) = target_component.as_ref() {
      if target.is_empty() {
        return Err(InvalidTargetNameError::new_err(format!(
          "Address `{original_spec}` from {description_of_origin} sets \
           the name component to the empty string, which is not legal."
        )));
      }
    } else if path_component.components().next().is_none() {
      return Err(InvalidTargetNameError::new_err(format!(
        "Address `{original_spec}` from {description_of_origin} has no name part, \
         but it's necessary because the path is the build root."
      )));
    }

    if path_component.components().next().is_some() && path_component.is_absolute() {
      return Err(InvalidSpecPathError::new_err(format!(
        "Invalid address {original_spec} from {description_of_origin}. Cannot use \
         absolute paths."
      )));
    }

    if let Some(parameters) = parameters.as_ref() {
      for (k, v) in parameters {
        let banned = k
          .chars()
          .chain(v.chars())
          .filter(|c| BANNED_CHARS_IN_PARAMETERS.contains(c))
          .map(|c| c.to_string())
          .collect::<Vec<_>>();
        if !banned.is_empty() {
          return Err(InvalidParametersError::new_err(format!(
            "Invalid address `{original_spec}` from {description_of_origin}. It has
               illegal characters in parameter entries: `{}` in `{k}={v}`.",
            banned.join(","),
          )));
        }
      }
    }

    Ok(Self {
      original_spec,
      path_component,
      target_component,
      generated_component,
      parameters: parameters.unwrap_or_default(),
      description_of_origin,
    })
  }

  #[classmethod]
  fn parse(
    _cls: &PyType,
    spec: &str,
    description_of_origin: &str,
    relative_to: Option<&str>,
    subproject_roots: Option<Vec<&str>>,
  ) -> PyResult<Self> {
    let subproject_info = subproject_roots
      .zip(relative_to)
      .and_then(|(roots, relative_to)| split_on_longest_dir_prefix(relative_to, &roots));

    let parsed_spec = address::parse_address_spec(spec).map_err(AddressParseException::new_err)?;
    if let Some(wildcard) = parsed_spec.wildcard {
      return Err(UnsupportedWildcardError::new_err(format!(
        "The address `{spec}` from {description_of_origin} ended in a wildcard \
        (`{wildcard}`), which is not supported."
      )));
    }
    let address = parsed_spec.address;

    let normalized_relative_to = if let Some((_, normalized_relative_to)) = subproject_info {
      Some(normalized_relative_to)
    } else {
      relative_to
    };

    let mut path_component: Cow<str> = address.path.into();
    if let Some(normalized_relative_to) = normalized_relative_to {
      if let Some(stripped) = path_component.strip_prefix("./") {
        path_component = format!(
          "{normalized_relative_to}{}{stripped}",
          std::path::MAIN_SEPARATOR
        )
        .into();
      }
      if path_component.is_empty() {
        path_component = normalized_relative_to.into();
      }
    }
    if let Some(stripped) = path_component.strip_prefix("//") {
      path_component = stripped.to_owned().into();
    }

    // NB: We confirm that the path_component is normalized while still in `str` form because
    // `Path` hides many of the components we're attempting to validate.
    if !path_component.is_empty() {
      for component in path_component.split(std::path::MAIN_SEPARATOR) {
        if matches!(component, "." | ".." | "") {
          return Err(InvalidSpecPathError::new_err(format!(
            "Invalid address `{spec}` from {description_of_origin}. It has an \
            un-normalized path part: `{component:?}`."
          )));
        }
      }
    }

    let path_component = if let Some((subproject, _)) = subproject_info {
      Path::new(subproject).join(Path::new(&*path_component))
    } else {
      PathBuf::from(path_component.into_owned())
    };

    Self::__new__(
      spec.to_owned(),
      path_component,
      description_of_origin.to_owned(),
      address.target.map(|t| t.to_owned()),
      address.generated.map(|t| t.to_owned()),
      Some(
        address
          .parameters
          .into_iter()
          .map(|(k, v)| (k.to_owned(), v.to_owned()))
          .collect(),
      ),
    )
  }

  #[getter]
  fn path_component(&self) -> &Path {
    &self.path_component
  }

  #[getter]
  fn target_component(&self) -> Option<&str> {
    self.target_component.as_deref()
  }

  #[getter]
  fn generated_component(&self) -> Option<&str> {
    self.generated_component.as_deref()
  }

  #[getter]
  fn parameters(&self) -> BTreeMap<String, String> {
    // TODO: For some reason, `IntoPy` is not implemented for `&BTreeMap<_, _>`.
    self.parameters.clone()
  }

  #[getter]
  fn description_of_origin(&self) -> &str {
    &self.description_of_origin
  }

  fn file_to_address(&self) -> PyResult<Address> {
    let Some(target_component) = self.target_component.as_ref() else {
      // Use the default target in the same directory as the file.
      match (
        self.path_component.parent(),
        self.path_component.file_name(),
      ) {
        (Some(spec_path), Some(relative_file_path)) if !spec_path.as_os_str().is_empty() => {
          return Address::__new__(
            spec_path.to_owned(),
            None,
            Some(self.parameters.clone()),
            None,
            Some(relative_file_path.into()),
          );
        }
        _ => {
          // We validate that this is not a top-level file. We couldn't do this earlier in the
          // AddressSpec constructor because we weren't sure if the path_spec referred to a file
          // vs. a directory.
          return Err(InvalidTargetNameError::new_err(format!(
            "Addresses for generated first-party targets in the build root must include \
             which target generator they come from, such as `{}:original_target`. However, \
             `{}` from {} did not have a target name.",
            self.path_component.display(),
            self.original_spec,
            self.description_of_origin,
          )));
        }
      }
    };

    // The target component may be "above" (but not below) the file in the filesystem.
    // Determine how many levels above the file it is, and validate that the path is relative.
    let parent_count = Path::new(&target_component).components().count() - 1;
    if parent_count == 0 {
      return Address::__new__(
        self
          .path_component
          .parent()
          .unwrap_or_else(|| Path::new(""))
          .to_owned(),
        Some(target_component.clone()),
        Some(self.parameters.clone()),
        None,
        self.path_component.file_name().map(|f| f.into()),
      );
    }

    if parent_count
      != Path::new(&target_component)
        .components()
        .take_while(|c| c.as_os_str() == OsStr::new(".."))
        .count()
    {
      return Err(InvalidTargetNameError::new_err(format!(
        "Invalid address `{}` from {}. The target name portion of the address must refer \
        to a target defined in the same directory or a parent directory of the file path \
        `{}`, but the value `{target_component}` is a subdirectory.",
        self.original_spec,
        self.description_of_origin,
        self.path_component.display(),
      )));
    }

    // Split the path_component into a spec_path and relative_file_path at the appropriate
    // position.
    let path_components = self
      .path_component
      .components()
      .map(|c| c.as_os_str().to_str().unwrap())
      .collect::<Vec<_>>();
    if path_components.len() <= parent_count {
      return Err(InvalidTargetNameError::new_err(format!(
        "Invalid address `{}` from {}. The target name portion of the address \
         `{target_component}` has too many `../`, which means it refers to a directory \
         above the file path `{}`. Expected no more than {} instances of `../` in
         `{target_component}`, but found {parent_count} instances.",
        self.original_spec,
        self.description_of_origin,
        self.path_component.display(),
        path_components.len(),
      )));
    }

    let offset = path_components.len() - (parent_count + 1);
    let spec_path = path_components[..offset].join(std::path::MAIN_SEPARATOR_STR);
    let relative_file_path = path_components[offset..].join(std::path::MAIN_SEPARATOR_STR);
    let target_name = Path::new(&target_component).file_name();
    Address::__new__(
      spec_path.into(),
      target_name.and_then(|t| t.to_str()).map(|t| t.to_owned()),
      Some(self.parameters.clone()),
      None,
      Some(relative_file_path.into()),
    )
  }

  fn dir_to_address(&self) -> PyResult<Address> {
    Address::__new__(
      self.path_component.clone(),
      self.target_component.clone(),
      Some(self.parameters.clone()),
      self.generated_component.clone(),
      None,
    )
  }

  #[getter]
  fn spec(&self) -> &str {
    &self.original_spec
  }

  fn __hash__(&self) -> u64 {
    let mut s = FnvHasher::default();
    self.hash(&mut s);
    s.finish()
  }

  fn __str__(&self) -> String {
    format!("{self:?}")
  }

  fn __repr__(&self) -> String {
    format!("{self:?}")
  }

  fn __richcmp__(&self, other: &Self, op: CompareOp, py: Python) -> PyObject {
    match op {
      CompareOp::Eq => (self == other).into_py(py),
      CompareOp::Ne => (self != other).into_py(py),
      _ => py.NotImplemented(),
    }
  }
}

fn split_on_longest_dir_prefix<'a, 'b>(
  path: &'a str,
  prefixes: &[&'b str],
) -> Option<(&'b str, &'a str)> {
  let mut longest_match = 0;
  let mut matched = None;
  for prefix in prefixes {
    if prefix.len() > longest_match {
      if let Ok(stripped) = Path::new(path).strip_prefix(prefix) {
        longest_match = prefix.len();
        matched = Some((*prefix, stripped.to_str().unwrap()));
      }
    }
  }
  matched
}

#[pyclass(name = "Address", weakref)]
#[derive(Clone, Hash, Eq, PartialEq, Ord, PartialOrd)]
pub struct Address {
  // NB: Field ordering is deliberate, so that Ord will roughly match `self.spec`.
  spec_path: PathBuf,
  relative_file_path: Option<PathBuf>,
  target_name: Option<String>,
  parameters: BTreeMap<String, String>,
  generated_name: Option<String>,
}

#[pymethods]
impl Address {
  #[new]
  fn __new__(
    spec_path: PathBuf,
    target_name: Option<String>,
    parameters: Option<BTreeMap<String, String>>,
    generated_name: Option<String>,
    relative_file_path: Option<PathBuf>,
  ) -> PyResult<Self> {
    if let Some(generated_name) = generated_name.as_ref() {
      if let Some(relative_file_path) = relative_file_path {
        return Err(PyAssertionError::new_err(format!(
          "Do not use both `generated_name` ({generated_name}) and \
                                      `relative_file_path` ({}).",
          relative_file_path.display()
        )));
      }
      let banned = generated_name
        .chars()
        .filter(|c| BANNED_CHARS_IN_GENERATED_NAME.contains(c))
        .map(|c| c.to_string())
        .collect::<Vec<_>>();
      if !banned.is_empty() {
        return Err(InvalidTargetNameError::new_err(format!(
          "The generated name `{generated_name}` (defined in directory {}, the part after \
          `#`) contains banned characters (`{}`). Please replace \
           these characters with another separator character like `_`, `-`, or `/`.",
          spec_path.display(),
          banned.join(","),
        )));
      }
    }

    let target_name = if let Some(target_name) = target_name {
      if Some(OsStr::new(&target_name)) == spec_path.file_name() {
        // If the target_name is the same as the default name would be, we normalize to None.
        None
      } else {
        let banned = target_name
          .chars()
          .filter(|c| BANNED_CHARS_IN_TARGET_NAME.contains(c))
          .map(|c| c.to_string())
          .collect::<Vec<_>>();
        if !banned.is_empty() {
          return Err(InvalidTargetNameError::new_err(format!(
            "The target name {target_name} (defined in directory {}) \
             contains banned characters (`{}`). Please replace \
             these characters with another separator character like `_` or `-`.",
            spec_path.display(),
            banned.join(","),
          )));
        }
        Some(target_name)
      }
    } else {
      None
    };

    let address = Self {
      spec_path,
      target_name,
      parameters: parameters.unwrap_or_default(),
      generated_name,
      relative_file_path,
    };

    if let Some(file_name) = address.spec_path.file_name().and_then(|n| n.to_str()) {
      if file_name.starts_with("BUILD") {
        return Err(InvalidSpecPathError::new_err(format!(
          "The address {address} has {} as the last part of its \
           path, but BUILD is a reserved name. Please make sure that you did not name any \
           directories BUILD.",
          Path::new(file_name).display(),
        )));
      }
    }

    Ok(address)
  }

  #[getter]
  fn spec_path(&self) -> &Path {
    &self.spec_path
  }

  #[getter]
  fn generated_name(&self) -> Option<&str> {
    self.generated_name.as_deref()
  }

  #[getter]
  fn relative_file_path(&self) -> Option<&Path> {
    self.relative_file_path.as_deref()
  }

  #[getter]
  fn parameters(&self) -> BTreeMap<String, String> {
    // TODO: For some reason, `IntoPy` is not implemented for `&BTreeMap<_, _>`.
    self.parameters.clone()
  }

  #[getter]
  pub fn is_generated_target(&self) -> bool {
    self.generated_name.is_some() || self.is_file_target()
  }

  #[getter]
  fn is_file_target(&self) -> bool {
    self.relative_file_path.is_some()
  }

  #[getter]
  fn is_parametrized(&self) -> bool {
    !self.parameters.is_empty()
  }

  fn is_parametrized_subset_of(&self, other: &Address) -> bool {
    self.equal_without_parameters(other)
      && self
        .parameters
        .iter()
        .all(|(k, v)| other.parameters.get(k) == Some(v))
  }

  #[getter]
  fn filename(&self) -> PyResult<PathBuf> {
    if let Some(relative_file_path) = self.relative_file_path.as_ref() {
      Ok(self.spec_path.join(relative_file_path))
    } else {
      Err(PyException::new_err(format!(
        "Only a file Address (`self.is_file_target`) has a filename: {self}",
      )))
    }
  }

  #[getter]
  fn target_name(&self) -> &str {
    if let Some(target_name) = self.target_name.as_ref() {
      target_name
    } else if let Some(file_name) = self.spec_path.file_name() {
      file_name
        .to_str()
        .unwrap_or_else(|| panic!("{} could not be viewed as UTF8.", self.spec_path.display()))
    } else {
      // TODO: This case is preserved from the original implementation (because `os.path.basename`
      // returns the empty output for an empty input), but should likely be ruled out in the
      // constructor.
      ""
    }
  }

  #[getter]
  fn parameters_repr(&self) -> Cow<str> {
    if self.parameters.is_empty() {
      return Cow::from("");
    }

    let rhs = self
      .parameters
      .iter()
      .map(|(k, v)| format!("{k}={v}"))
      .collect::<Vec<_>>()
      .join(",");
    Cow::from(format!("@{rhs}"))
  }

  #[getter]
  fn spec(&self) -> String {
    let prefix = if self.spec_path.as_os_str().is_empty() {
      "//"
    } else {
      ""
    };

    let (path, target): (Cow<Path>, Cow<str>) =
      if let Some(relative_file_path) = self.relative_file_path.as_ref() {
        let parent_prefix = "../".repeat(relative_file_path.components().count() - 1);
        let target = if self.target_name.is_none() && parent_prefix.is_empty() {
          ""
        } else {
          self.target_name()
        };
        (
          self.spec_path.join(relative_file_path).into(),
          format!("{parent_prefix}{target}").into(),
        )
      } else {
        let target_name = if self.target_name.is_none()
          && (self.generated_name.is_some() || !self.parameters.is_empty())
        {
          "".into()
        } else {
          self.target_name().into()
        };
        ((&self.spec_path).into(), target_name)
      };

    let target_sep = if target.is_empty() { "" } else { ":" };
    let generated: Cow<str> = if let Some(generated_name) = self.generated_name.as_ref() {
      format!("#{generated_name}").into()
    } else {
      "".into()
    };

    format!(
      "{prefix}{}{target_sep}{target}{generated}{}",
      path.display(),
      self.parameters_repr()
    )
  }

  #[getter]
  fn path_safe_spec(&self) -> PyResult<String> {
    fn sanitize<D: std::fmt::Display>(s: D) -> String {
      s.to_string().replace(std::path::MAIN_SEPARATOR, ".")
    }

    let (parent_prefix, path): (Cow<str>, Cow<str>) = match self.relative_file_path.as_ref() {
      Some(relative_file_path) if !relative_file_path.as_os_str().is_empty() => {
        let parent_count = relative_file_path.components().count() - 1;
        let parent_prefix = if parent_count > 0 {
          "@".repeat(parent_count).into()
        } else {
          ".".into()
        };
        (
          parent_prefix,
          format!(".{}", sanitize(relative_file_path.display())).into(),
        )
      }
      _ => (".".into(), "".into()),
    };

    let target: Cow<str> = if parent_prefix == "." {
      if let Some(target_name) = self.target_name.as_ref() {
        format!("{parent_prefix}{target_name}").into()
      } else {
        "".into()
      }
    } else {
      format!("{parent_prefix}{}", self.target_name()).into()
    };

    let params: Cow<str> = if self.parameters.is_empty() {
      "".into()
    } else {
      format!("@{}", sanitize(self.parameters_repr())).into()
    };

    let generated: Cow<str> = if let Some(generated_name) = self.generated_name.as_ref() {
      format!("@{}", sanitize(generated_name)).into()
    } else {
      "".into()
    };

    let prefix = sanitize(self.spec_path.display());

    Ok(format!("{prefix}{path}{target}{generated}{params}"))
  }

  fn parametrize(&self, parameters: BTreeMap<String, String>) -> Self {
    let mut merged_parameters = self.parameters.clone();
    merged_parameters.extend(parameters);

    Self {
      spec_path: self.spec_path.clone(),
      target_name: self.target_name.clone(),
      parameters: merged_parameters,
      generated_name: self.generated_name.clone(),
      relative_file_path: self.relative_file_path.clone(),
    }
  }

  fn maybe_convert_to_target_generator(self_: PyRef<Self>, py: Python) -> PyObject {
    if !self_.is_generated_target() && !self_.is_parametrized() {
      return self_.into_py(py);
    }

    Self {
      spec_path: self_.spec_path.clone(),
      target_name: self_.target_name.clone(),
      parameters: BTreeMap::default(),
      generated_name: None,
      relative_file_path: None,
    }
    .into_py(py)
  }

  fn create_generated(&self, generated_name: String) -> PyResult<Self> {
    if self.is_generated_target() {
      return Err(PyAssertionError::new_err(format!(
        "Cannot call `create_generated` on `{self}`."
      )));
    }

    Ok(Self {
      spec_path: self.spec_path.clone(),
      target_name: self.target_name.clone(),
      parameters: self.parameters.clone(),
      generated_name: Some(generated_name),
      relative_file_path: None,
    })
  }

  fn create_file(&self, relative_file_path: PathBuf) -> PyResult<Self> {
    if self.is_generated_target() {
      return Err(PyAssertionError::new_err(format!(
        "Cannot call `create_file` on `{self}`."
      )));
    }

    Ok(Self {
      spec_path: self.spec_path.clone(),
      target_name: self.target_name.clone(),
      parameters: self.parameters.clone(),
      generated_name: None,
      relative_file_path: Some(relative_file_path),
    })
  }

  fn debug_hint(&self) -> String {
    self.spec()
  }

  fn metadata<'p>(&self, py: Python<'p>) -> PyResult<&'p PyDict> {
    let dict = PyDict::new(py);
    dict.set_item(pyo3::intern!(py, "address"), self.spec())?;
    Ok(dict)
  }

  fn __hash__(&self) -> u64 {
    let mut s = FnvHasher::default();
    self.hash(&mut s);
    s.finish()
  }

  fn __str__(&self) -> String {
    format!("{self}")
  }

  fn __repr__(&self) -> String {
    format!("Address({self})")
  }

  fn __richcmp__(&self, other: &Self, op: CompareOp) -> bool {
    op.matches(self.cmp(other))
  }
}

impl Address {
  fn equal_without_parameters(&self, other: &Address) -> bool {
    self.spec_path == other.spec_path
      && self.target_name == other.target_name
      && self.generated_name == other.generated_name
      && self.relative_file_path == other.relative_file_path
  }
}

impl std::fmt::Display for Address {
  fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
    write!(f, "{}", self.spec())
  }
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

/// Parses an "address spec" from the CLI.
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
