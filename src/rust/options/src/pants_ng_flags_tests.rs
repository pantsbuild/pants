// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::{
    BuildRoot, DictEdit, DictEditAction, ListEdit, ListEditAction, OptionsSource, Scope, Val,
    fromfile::FromfileExpander, option_id, pants_ng_flags::PantsNgFlagsReader,
};
use maplit::hashmap;
use std::path::PathBuf;

#[test]
fn test_flags() {
    let flags = hashmap! {
        Scope::Global => hashmap! {
            "bool_flag1".to_string() => vec![None],
            "bool_flag2".to_string() => vec![Some("false".to_string())],
            "string_flag".to_string() => vec![Some("stringval".to_string())],
            "int_flag".to_string() => vec![Some("42".to_string())],
            "float_flag".to_string() => vec![Some("3.14159".to_string())],
            "list_flag1".to_string() => vec![Some("el1".to_string()), Some("el2".to_string())],
            "list_flag2".to_string() => vec![Some("[0,1]".to_string()), Some("-[2,3]".to_string())],
            "dict_flag".to_string() => vec![Some("{\"foo\":0,\"bar\":1}".to_string())],
        },
    };
    let flags_reader = PantsNgFlagsReader::new(
        flags,
        FromfileExpander::relative_to(BuildRoot::for_path(PathBuf::from("."))),
    );

    assert_eq!(
        flags_reader.get_string(&option_id!("string_flag")),
        Ok(Some("stringval".to_string()))
    );

    assert_eq!(
        flags_reader.get_bool(&option_id!("bool_flag1")),
        Ok(Some(true))
    );

    assert_eq!(
        flags_reader.get_bool(&option_id!("bool_flag2")),
        Ok(Some(false))
    );

    assert_eq!(flags_reader.get_int(&option_id!("int_flag")), Ok(Some(42)));

    assert_eq!(
        flags_reader.get_float(&option_id!("float_flag")),
        Ok(Some(3.14159))
    );

    assert_eq!(
        flags_reader.get_string_list(&option_id!("list_flag1")),
        Ok(Some(vec![
            ListEdit {
                action: ListEditAction::Add,
                items: vec!["el1".to_string()]
            },
            ListEdit {
                action: ListEditAction::Add,
                items: vec!["el2".to_string()]
            }
        ]))
    );

    assert_eq!(
        flags_reader.get_int_list(&option_id!("list_flag2")),
        Ok(Some(vec![
            ListEdit {
                action: ListEditAction::Replace,
                items: vec![0, 1]
            },
            ListEdit {
                action: ListEditAction::Remove,
                items: vec![2, 3]
            }
        ]))
    );

    assert_eq!(
        flags_reader.get_dict(&option_id!("dict_flag")),
        Ok(Some(vec![DictEdit {
            action: DictEditAction::Replace,
            items: hashmap! {"foo".to_string() => Val::Int(0), "bar".to_string() => Val::Int(1)}
        }]))
    );
}
