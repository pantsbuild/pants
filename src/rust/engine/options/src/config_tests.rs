// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use regex::Regex;
use std::collections::HashMap;
use std::fs::File;
use std::io::Write;

use crate::config::{interpolate_string, Config};
use crate::{option_id, DictEdit, DictEditAction, ListEdit, ListEditAction, OptionsSource, Val};

use tempfile::TempDir;

fn maybe_config(file_content: &'static str) -> Result<Config, String> {
    let dir = TempDir::new().unwrap();
    let path = dir.path().join("pants.toml");
    File::create(&path)
        .unwrap()
        .write_all(file_content.as_bytes())
        .unwrap();
    Config::parse(
        &path,
        &HashMap::from([
            ("seed1".to_string(), "seed1val".to_string()),
            ("seed2".to_string(), "seed2val".to_string()),
        ]),
    )
}

fn config(file_content: &'static str) -> Config {
    maybe_config(file_content).unwrap()
}

#[test]
fn test_display() {
    let config = config("");
    assert_eq!(
        "[GLOBAL] name".to_owned(),
        config.display(&option_id!("name"))
    );
    assert_eq!(
        "[scope] name".to_owned(),
        config.display(&option_id!(["scope"], "name"))
    );
    assert_eq!(
        "[scope] full_name".to_owned(),
        config.display(&option_id!(-'f', ["scope"], "full", "name"))
    );
}

#[test]
fn test_interpolate_string() {
    fn interp(
        template: &str,
        interpolations: Vec<(&'static str, &'static str)>,
    ) -> Result<String, String> {
        let interpolation_map: HashMap<_, _> = interpolations
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect();
        interpolate_string(template.to_string(), &interpolation_map)
    }

    let template = "%(greeting)s world, what's your %(thing)s?";
    let replacements = vec![("greeting", "Hello"), ("thing", "deal")];
    assert_eq!(
        "Hello world, what's your deal?",
        interp(template, replacements).unwrap()
    );

    let template = "abc %(d5f_g)s hij";
    let replacements = vec![("d5f_g", "defg"), ("unused", "xxx")];
    assert_eq!("abc defg hij", interp(template, replacements).unwrap());

    let template = "%(known)s %(unknown)s";
    let replacements = vec![("known", "aaa"), ("unused", "xxx")];
    let result = interp(template, replacements);
    assert!(result.is_err());
    assert_eq!(
        "Unknown value for placeholder `unknown`",
        result.unwrap_err()
    );

    let template = "%(greeting)s world, what's your %(thing)s?";
    let replacements = vec![
        ("greeting", "Hello"),
        ("thing", "real %(deal)s"),
        ("deal", "name"),
    ];
    assert_eq!(
        "Hello world, what's your real name?",
        interp(template, replacements).unwrap()
    );
}

#[test]
fn test_interpolate_config() {
    let conf = config(
        "[DEFAULT]\n\
     field1 = 'something'\n\
     color = 'black'\n\
     [foo]\n\
     field2 = '%(field1)s else'\n\
     field3 = 'entirely'\n\
     field4 = '%(field2)s %(field3)s %(seed2)s'\n\
     [groceries]\n\
     berryprefix = 'straw'\n\
     stringlist.add = ['apple', '%(berryprefix)sberry', 'banana']\n\
     stringlist.remove = ['%(color)sberry', 'pear']\n\
     inline_table = { fruit = '%(berryprefix)sberry', spice = '%(color)s pepper' }",
    );

    assert_eq!(
        "something else entirely seed2val",
        conf.get_string(&option_id!(["foo"], "field4"))
            .unwrap()
            .unwrap()
    );

    assert_eq!(
        vec![
            ListEdit {
                action: ListEditAction::Add,
                items: vec![
                    "apple".to_string(),
                    "strawberry".to_string(),
                    "banana".to_string(),
                ],
            },
            ListEdit {
                action: ListEditAction::Remove,
                items: vec!["blackberry".to_string(), "pear".to_string()]
            }
        ],
        conf.get_string_list(&option_id!(["groceries"], "stringlist"))
            .unwrap()
            .unwrap()
    );

    assert_eq!(
        DictEdit {
            action: DictEditAction::Replace,
            items: HashMap::from([
                ("fruit".to_string(), Val::String("strawberry".to_string())),
                ("spice".to_string(), Val::String("black pepper".to_string()))
            ])
        },
        conf.get_dict(&option_id!(["groceries"], "inline_table"))
            .unwrap()
            .unwrap()
    );

    let bad_conf = maybe_config(
        "[DEFAULT]\n\
     field1 = 'something'\n\
     [foo]\n\
     bad_field = '%(unknown)s'\n",
    );
    let err_msg = bad_conf.err().unwrap();
    let pat =
        r"^Unknown value for placeholder `unknown` in config file .*, section foo, key bad_field$";
    assert!(
        Regex::new(pat).unwrap().is_match(&err_msg),
        "Error message:  {}\nDid not match: {}",
        &err_msg,
        pat
    );
}
