// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::scope::Scope;
use std::fmt;
use std::fmt::{Display, Formatter};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OptionId {
    pub(crate) scope: Scope,
    pub(crate) name_components: Vec<String>,
    pub(crate) short_name: Option<String>,
}

impl OptionId {
    pub fn new<Component, Name>(
        scope: Scope,
        name: Name,
        short_name: Option<char>,
    ) -> Result<OptionId, String>
    where
        Component: AsRef<str>,
        Name: Iterator<Item = Component>,
    {
        let name_components = name
            .map(|component| component.as_ref().to_string())
            .collect::<Vec<_>>();
        if name_components.is_empty() {
            return Err(format!(
                "Cannot create an OptionId with an empty name. Given a scope of {scope:?}."
            ));
        }
        Ok(OptionId {
            scope,
            name_components,
            short_name: short_name.map(|c| c.to_string()),
        })
    }
}

impl Display for OptionId {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "[{}] {}",
            self.scope.name(),
            self.name("_", NameTransform::None)
        )
    }
}

#[macro_export]
macro_rules! option_id {
    (-$switch:literal, [$scope:literal], $($name_component:literal),+) => {
        $crate::OptionId::new(
            $crate::Scope::named($scope),
            [$($name_component),+].iter(),
            Some($switch)
        ).expect("Creating an OptionId via macro should ensure at least one name component")
    };
    (-$switch:literal, $($name_component:literal),+) => {
        $crate::OptionId::new(
            $crate::Scope::Global,
            [$($name_component),+].iter(),
            Some($switch)
        ).expect("Creating an OptionId via macro should ensure at least one name component")
    };
    ([$scope:literal], $($name_component:literal),+) => {
        $crate::OptionId::new(
            $crate::Scope::named($scope),
            [$($name_component),+].iter(),
            None
        ).expect("Creating an OptionId via macro should ensure at least one name component")
    };
    ($($name_component:literal),+) => {
        $crate::OptionId::new(
            $crate::Scope::Global,
            [$($name_component),+].iter(),
            None
        ).expect("Creating an OptionId via macro should ensure at least one name component")
    };
}

pub(crate) enum NameTransform {
    None,
    ToLower,
    ToUpper,
}

impl OptionId {
    pub(crate) fn name(&self, sep: &str, transform: NameTransform) -> String {
        self.name_components
            .iter()
            .map(|component| match transform {
                NameTransform::None => component.to_owned(),
                NameTransform::ToLower => component.to_ascii_lowercase(),
                NameTransform::ToUpper => component.to_ascii_uppercase(),
            })
            .collect::<Vec<_>>()
            .join(sep)
    }

    pub(crate) fn name_components_strs(&self) -> impl Iterator<Item = &str> {
        self.name_components.iter().map(|s| s.as_ref())
    }

    pub fn name_underscored(&self) -> String {
        self.name("_", NameTransform::None)
    }
}
