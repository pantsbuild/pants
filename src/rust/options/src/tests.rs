// Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::config::ConfigSource;
use crate::flags::Flag;
use crate::{
    Args, BuildRoot, DictEdit, DictEditAction, Env, GoalInfo, ListEdit, ListEditAction,
    OptionParser, Scope, Source, Val, munge_bin_name, option_id,
};
use itertools::Itertools;
use maplit::{btreemap, hashmap, hashset};
use std::collections::{BTreeMap, HashMap};
use std::fs::File;
use std::io::Write;
use std::path::PathBuf;
use tempfile::TempDir;

fn config_source() -> Source {
    Source::Config {
        ordinal: 0,
        path: "pants.toml".to_string(),
    }
}

fn extra_config_source() -> Source {
    Source::Config {
        ordinal: 1,
        path: "pants_extra.toml".to_string(),
    }
}

fn with_setup(
    args: Vec<&'static str>,
    env: Vec<(&'static str, &'static str)>,
    config: &'static str,
    extra_config: &'static str,
    do_check: impl Fn(OptionParser),
) {
    let buildroot = TempDir::new().unwrap();
    let config_path = buildroot.path().join("pants.toml");
    File::create(&config_path)
        .unwrap()
        .write_all(config.as_bytes())
        .unwrap();
    let extra_config_path = buildroot.path().join("pants_extra.toml");
    File::create(&extra_config_path)
        .unwrap()
        .write_all(extra_config.as_bytes())
        .unwrap();
    let config_file_arg = vec![format!(
        "--pants-config-files={}",
        extra_config_path.to_str().unwrap()
    )];

    fn mk_goal(name: &str) -> GoalInfo {
        GoalInfo {
            scope_name: name.to_string(),
            is_builtin: false,
            is_auxiliary: false,
            aliases: vec![],
        }
    }

    let option_parser = OptionParser::new(
        Args::new(
            config_file_arg
                .into_iter()
                .chain(args.into_iter().map(str::to_string)),
        ),
        Env {
            env: env
                .into_iter()
                .map(|(k, v)| (k.to_owned(), v.to_owned()))
                .collect::<BTreeMap<_, _>>(),
        },
        Some(
            [config_path, extra_config_path]
                .iter()
                .map(|cp| ConfigSource::from_file(cp).unwrap())
                .collect(),
        ),
        false,
        true,
        Some(BuildRoot::find_from(buildroot.path()).unwrap()),
        None,
        Some(vec![
            mk_goal("test"),
            mk_goal("fmt"),
            mk_goal("lint"),
            mk_goal("check"),
            mk_goal("repl"),
        ]),
    )
    .unwrap();
    do_check(option_parser);
}

#[test]
fn test_source_ordering() {
    assert!(
        Source::Default
            < Source::Config {
                ordinal: 0,
                path: "pants.toml".to_string()
            }
    );
    assert!(
        Source::Config {
            ordinal: 0,
            path: "pants.toml".to_string()
        } < Source::Config {
            ordinal: 1,
            path: "extra_pants.toml".to_string()
        }
    );
    assert!(
        Source::Config {
            ordinal: 1,
            path: "extra_pants.toml".to_string()
        } < Source::Env
    );
    assert!(Source::Env < Source::Flag);
}

#[test]
fn test_parse_single_valued_options() {
    fn check(
        expected: i64,
        expected_derivation: Vec<(&Source, i64)>,
        args: Vec<&'static str>,
        env: Vec<(&'static str, &'static str)>,
        config: &'static str,
    ) {
        with_setup(args, env, config, "", |option_parser| {
            let id = option_id!(["scope"], "foo");
            let option_value = option_parser.parse_int(&id, 0).unwrap();
            assert_eq!(expected, option_value.value);
            assert_eq!(expected_derivation, option_value.derivation.unwrap());
        });
    }

    check(
        3,
        vec![
            (&Source::Default, 0),
            (&config_source(), 1),
            (&Source::Env, 2),
            (&Source::Flag, 3),
        ],
        vec!["--scope-foo=3"],
        vec![("PANTS_SCOPE_FOO", "2")],
        "[scope]\nfoo = 1",
    );
    check(
        3,
        vec![(&Source::Default, 0), (&Source::Env, 2), (&Source::Flag, 3)],
        vec!["--scope-foo=3"],
        vec![("PANTS_SCOPE_FOO", "2")],
        "",
    );
    check(
        3,
        vec![
            (&Source::Default, 0),
            (&config_source(), 1),
            (&Source::Flag, 3),
        ],
        vec!["--scope-foo=3"],
        vec![],
        "[scope]\nfoo = 1",
    );
    check(
        2,
        vec![
            (&Source::Default, 0),
            (&config_source(), 1),
            (&Source::Env, 2),
        ],
        vec![],
        vec![("PANTS_SCOPE_FOO", "2")],
        "[scope]\nfoo = 1",
    );
    check(
        2,
        vec![(&Source::Default, 0), (&Source::Env, 2)],
        vec![],
        vec![("PANTS_SCOPE_FOO", "2")],
        "",
    );
    check(
        1,
        vec![(&Source::Default, 0), (&config_source(), 1)],
        vec![],
        vec![],
        "[scope]\nfoo = 1",
    );
    check(0, vec![(&Source::Default, 0)], vec![], vec![], "");
}

#[test]
fn test_parse_list_options() {
    fn check(
        expected: Vec<i64>,
        expected_derivation: Vec<(&Source, Vec<ListEdit<i64>>)>,
        args: Vec<&'static str>,
        env: Vec<(&'static str, &'static str)>,
        config: &'static str,
        extra_config: &'static str,
    ) {
        with_setup(args, env, config, extra_config, |option_parser| {
            let id = option_id!(["scope"], "foo");
            let option_value = option_parser.parse_int_list(&id, vec![0]).unwrap();
            assert_eq!(expected, option_value.value);
            assert_eq!(expected_derivation, option_value.derivation.unwrap());
        });
    }

    fn replace(items: Vec<i64>) -> ListEdit<i64> {
        ListEdit {
            action: ListEditAction::Replace,
            items,
        }
    }

    fn add(items: Vec<i64>) -> ListEdit<i64> {
        ListEdit {
            action: ListEditAction::Add,
            items,
        }
    }

    fn remove(items: Vec<i64>) -> ListEdit<i64> {
        ListEdit {
            action: ListEditAction::Remove,
            items,
        }
    }

    check(
        vec![0, 1, 2, 3, 4, 5, 6, 7],
        vec![
            (&Source::Default, vec![replace(vec![0])]),
            (&config_source(), vec![add(vec![1, 2])]),
            (&Source::Env, vec![add(vec![3, 4])]),
            (&Source::Flag, vec![add(vec![5, 6, 7])]),
        ],
        vec!["--scope-foo=+[5, 6, 7]"],
        vec![("PANTS_SCOPE_FOO", "+[3, 4]")],
        "[scope]\nfoo.add = [1, 2]",
        "",
    );

    check(
        vec![1, 2, 3, 4, 5, 6, 7],
        vec![
            (&Source::Default, vec![replace(vec![0])]),
            (&config_source(), vec![replace(vec![1, 2])]),
            (&Source::Env, vec![add(vec![3, 4])]),
            (&Source::Flag, vec![add(vec![5, 6, 7])]),
        ],
        vec!["--scope-foo=+[5, 6, 7]"],
        vec![("PANTS_SCOPE_FOO", "+[3, 4]")],
        "[scope]\nfoo = [1, 2]",
        "",
    );

    check(
        vec![3, 4, 5, 6, 7],
        vec![
            (&Source::Default, vec![replace(vec![0])]),
            (&config_source(), vec![add(vec![1, 2])]),
            (&Source::Env, vec![replace(vec![3, 4])]),
            (&Source::Flag, vec![add(vec![5, 6, 7])]),
        ],
        vec!["--scope-foo=+[5, 6, 7]"],
        vec![("PANTS_SCOPE_FOO", "[3, 4]")],
        "[scope]\nfoo.add = [1, 2]",
        "",
    );

    check(
        vec![5, 6, 7],
        vec![
            (&Source::Default, vec![replace(vec![0])]),
            (&config_source(), vec![add(vec![1, 2])]),
            (&Source::Env, vec![add(vec![3, 4])]),
            (&Source::Flag, vec![replace(vec![5, 6, 7])]),
        ],
        vec!["--scope-foo=[5, 6, 7]"],
        vec![("PANTS_SCOPE_FOO", "+[3, 4]")],
        "[scope]\nfoo.add = [1, 2]",
        "",
    );

    check(
        vec![0, 1, 2, 11, 22, 3, 4],
        vec![
            (&Source::Default, vec![replace(vec![0])]),
            (&config_source(), vec![add(vec![1, 2])]),
            (&extra_config_source(), vec![add(vec![11, 22])]),
            (&Source::Env, vec![add(vec![3, 4])]),
        ],
        vec![],
        vec![("PANTS_SCOPE_FOO", "+[3, 4]")],
        "[scope]\nfoo = \"+[1, 2]\"",
        "[scope]\nfoo = \"+[11, 22]\"",
    );

    check(
        vec![1, 3],
        vec![
            (&Source::Default, vec![replace(vec![0])]),
            (&config_source(), vec![replace(vec![1, 2])]),
            (&extra_config_source(), vec![remove(vec![2, 4])]),
            (&Source::Env, vec![add(vec![3, 4])]),
        ],
        vec![],
        vec![("PANTS_SCOPE_FOO", "+[3, 4]")],
        "[scope]\nfoo = [1, 2]",
        "[scope]\nfoo = '-[2, 4]'",
    );

    check(
        vec![0, 3, 4],
        vec![
            (&Source::Default, vec![replace(vec![0])]),
            (&Source::Env, vec![add(vec![3, 4])]),
        ],
        vec![],
        vec![("PANTS_SCOPE_FOO", "+[3, 4]")],
        "",
        "",
    );

    check(
        vec![0, 1, 3, 4, 5, 6, 7],
        vec![
            (&Source::Default, vec![replace(vec![0])]),
            (&config_source(), vec![add(vec![1, 2])]),
            (&Source::Env, vec![remove(vec![2]), add(vec![3, 4])]),
            (&Source::Flag, vec![add(vec![5, 6, 7])]),
        ],
        vec!["--scope-foo=+[5, 6, 7]"],
        vec![("PANTS_SCOPE_FOO", "-[2],+[3, 4]")],
        "[scope]\nfoo.add = [1, 2]",
        "",
    );

    check(
        vec![0, 5, 6, 7],
        vec![
            (&Source::Default, vec![replace(vec![0])]),
            (&Source::Flag, vec![add(vec![5, 6, 7])]),
        ],
        vec!["--scope-foo=+[5, 6, 7]"],
        vec![],
        "",
        "",
    );

    // Filtering all instances of repeated values.
    check(
        vec![1, 2, 2, 4],
        vec![
            (&Source::Default, vec![replace(vec![0])]),
            (&config_source(), vec![add(vec![1, 2, 3, 2, 0, 3, 3, 4])]),
            (&Source::Env, vec![remove(vec![0, 3])]),
        ],
        vec![],
        vec![("PANTS_SCOPE_FOO", "-[0, 3]")],
        "[scope]\nfoo.add = [1, 2, 3, 2, 0, 3, 3, 4]",
        "",
    );

    // Filtering a value even though it was appended again at a higher rank.
    check(
        vec![0, 2],
        vec![
            (&Source::Default, vec![replace(vec![0])]),
            (&config_source(), vec![add(vec![1, 2])]),
            (&Source::Env, vec![remove(vec![1])]),
            (&Source::Flag, vec![add(vec![1])]),
        ],
        vec!["--scope-foo=+[1]"],
        vec![("PANTS_SCOPE_FOO", "-[1]")],
        "[scope]\nfoo.add = [1, 2]",
        "",
    );

    // Filtering a value even though it was appended again at the same rank.
    check(
        vec![0, 2],
        vec![
            (&Source::Default, vec![replace(vec![0])]),
            (&config_source(), vec![add(vec![1, 2])]),
            (&Source::Env, vec![remove(vec![1]), add(vec![1])]),
        ],
        vec![],
        vec![("PANTS_SCOPE_FOO", "-[1],+[1]")],
        "[scope]\nfoo.add = [1, 2]",
        "",
    );

    // Overwriting cancels filters.
    check(
        vec![0],
        vec![
            (&Source::Default, vec![replace(vec![0])]),
            (&config_source(), vec![remove(vec![0])]),
            (&Source::Env, vec![replace(vec![0])]),
        ],
        vec![],
        vec![("PANTS_SCOPE_FOO", "[0]")],
        "[scope]\nfoo.remove = [0]",
        "",
    );
}

#[test]
fn test_parse_dict_options() {
    fn with_owned_keys(dict: HashMap<&str, Val>) -> HashMap<String, Val> {
        dict.into_iter().map(|(k, v)| (k.to_string(), v)).collect()
    }

    fn check(
        expected: HashMap<&str, Val>,
        expected_derivation: Vec<(&Source, Vec<DictEdit>)>,
        args: Vec<&'static str>,
        env: Vec<(&'static str, &'static str)>,
        config: &'static str,
        extra_config: &'static str,
    ) {
        let expected = with_owned_keys(expected);
        with_setup(args, env, config, extra_config, |option_parser| {
            let id = option_id!(["scope"], "foo");
            let default = HashMap::from([
                ("key1".to_string(), Val::Int(1)),
                ("key2".to_string(), Val::String("val2".to_string())),
            ]);
            let option_value = option_parser.parse_dict(&id, default).unwrap();
            assert_eq!(expected, option_value.value);
            assert_eq!(expected_derivation, option_value.derivation.unwrap())
        });
    }

    fn replace(items: HashMap<&str, Val>) -> Vec<DictEdit> {
        vec![DictEdit {
            action: DictEditAction::Replace,
            items: with_owned_keys(items),
        }]
    }

    fn add(items: HashMap<&str, Val>) -> Vec<DictEdit> {
        vec![DictEdit {
            action: DictEditAction::Add,
            items: with_owned_keys(items),
        }]
    }

    fn add2(items0: HashMap<&str, Val>, items1: HashMap<&str, Val>) -> Vec<DictEdit> {
        vec![
            DictEdit {
                action: DictEditAction::Add,
                items: with_owned_keys(items0),
            },
            DictEdit {
                action: DictEditAction::Add,
                items: with_owned_keys(items1),
            },
        ]
    }

    let default_derivation = (
        &Source::Default,
        replace(hashmap! {"key1" => Val::Int(1), "key2" => Val::String("val2".to_string())}),
    );

    check(
        hashmap! {
            "key1" => Val::Int(1),
            "key2" => Val::String("val2".to_string()),
            "key3" => Val::Int(3),
            "key3a" => Val::String("3a".to_string()),
            "key4" => Val::Float(4.0),
            "key5" => Val::Bool(true),
            "key6" => Val::Int(6),
        },
        vec![
            default_derivation.clone(),
            (&config_source(), add(hashmap! {"key5" => Val::Bool(true)})),
            (
                &extra_config_source(),
                add(hashmap! {"key6" => Val::Int(6)}),
            ),
            (&Source::Env, add(hashmap! {"key4" => Val::Float(4.0)})),
            (
                &Source::Flag,
                add2(
                    hashmap! {"key3" => Val::Int(3)},
                    hashmap! {"key3a" => Val::String("3a".to_string())},
                ),
            ),
        ],
        vec!["--scope-foo=+{'key3': 3}", "--scope-foo=+{'key3a': '3a'}"],
        vec![("PANTS_SCOPE_FOO", "+{'key4': 4.0}")],
        "[scope]\nfoo = \"+{ 'key5': true }\"",
        "[scope]\nfoo = \"+{ 'key6': 6 }\"",
    );

    check(
        hashmap! {
            "key3" => Val::Int(3),
            "key4" => Val::Float(4.0),
            "key6" => Val::Int(6),
        },
        vec![
            default_derivation.clone(),
            (&config_source(), add(hashmap! {"key5" => Val::Bool(true)})),
            (
                &extra_config_source(),
                replace(hashmap! {"key6" => Val::Int(6)}),
            ),
            (&Source::Env, add(hashmap! {"key4" => Val::Float(4.0)})),
            (&Source::Flag, add(hashmap! {"key3" => Val::Int(3)})),
        ],
        vec!["--scope-foo=+{'key3': 3}"],
        vec![("PANTS_SCOPE_FOO", "+{'key4': 4.0}")],
        "[scope]\nfoo = \"+{ 'key5': true }\"",
        "[scope.foo]\nkey6 = 6",
    );

    check(
        hashmap! {
            "key3" => Val::Int(3),
            "key4" => Val::Float(4.0),
        },
        vec![
            default_derivation.clone(),
            (&config_source(), add(hashmap! {"key5" => Val::Bool(true)})),
            (
                &extra_config_source(),
                replace(hashmap! {"key6" => Val::Int(6)}),
            ),
            (&Source::Env, replace(hashmap! {"key4" => Val::Float(4.0)})),
            (&Source::Flag, add(hashmap! {"key3" => Val::Int(3)})),
        ],
        vec!["--scope-foo=+{'key3': 3}"],
        vec![("PANTS_SCOPE_FOO", "{'key4': 4.0}")],
        "[scope]\nfoo = \"+{ 'key5': true }\"",
        "[scope.foo]\nkey6 = 6",
    );

    check(
        hashmap! {
            "key3" => Val::Int(3),
        },
        vec![
            default_derivation.clone(),
            (&config_source(), add(hashmap! {"key5" => Val::Bool(true)})),
            (
                &extra_config_source(),
                replace(hashmap! {"key6" => Val::Int(6)}),
            ),
            (&Source::Env, replace(hashmap! {"key4" => Val::Float(4.0)})),
            (&Source::Flag, replace(hashmap! {"key3" => Val::Int(3)})),
        ],
        vec!["--scope-foo={'key3': 3}"],
        vec![("PANTS_SCOPE_FOO", "{'key4': 4.0}")],
        "[scope]\nfoo = \"+{ 'key5': true }\"",
        "[scope.foo]\nkey6 = 6",
    );

    check(
        hashmap! {
            "key1" => Val::Int(1),
            "key2" => Val::String("val2".to_string()),
        },
        vec![default_derivation],
        vec![],
        vec![],
        "",
        "",
    );
}

#[test]
fn test_do_not_load_pantsrc_if_configs_passed() {
    fn mk_args() -> Args {
        Args::new(vec![])
    }
    fn mk_env() -> Env {
        Env {
            env: BTreeMap::new(),
        }
    }

    let load_0 = OptionParser::new(
        mk_args(),
        mk_env(),
        Some(vec![]),
        true,
        true,
        None,
        None,
        None,
    );

    let found_sources = load_0.unwrap().sources;
    println!("{:?}", found_sources.keys());
    assert_eq!(
        vec![Source::Env, Source::Flag],
        found_sources.keys().cloned().collect_vec()
    )
}

#[test]
fn test_validate_config() {
    with_setup(
        vec![],
        vec![],
        "[foo]\nbar = 0",
        "[baz]\nqux = 0",
        |option_parser| {
            assert_eq!(
                vec![
                    "Invalid table name [foo] in pants.toml".to_string(),
                    "Invalid table name [baz] in pants_extra.toml".to_string()
                ],
                option_parser.validate_config(&hashmap! {})
            )
        },
    );

    with_setup(
        vec![],
        vec![],
        "[foo]\nbar = 0",
        "[baz]\nqux = 0",
        |option_parser| {
            assert_eq!(
                vec!["Invalid option 'bar' under [foo] in pants.toml".to_string(),],
                option_parser.validate_config(&hashmap! {
                    "foo".to_string() => hashset! {"other".to_string()},
                    "baz".to_string() => hashset! {"qux".to_string()},
                })
            )
        },
    );

    let empty: Vec<String> = vec![];
    with_setup(
        vec![],
        vec![],
        "[foo]\nbar = 0",
        "[baz]\nqux = 0",
        |option_parser| {
            assert_eq!(
                empty,
                option_parser.validate_config(&hashmap! {
                    "foo".to_string() => hashset! {"bar".to_string()},
                    "baz".to_string() => hashset! {"qux".to_string()},
                })
            )
        },
    );
}

#[test]
fn test_config_path_discovery() {
    let buildroot = TempDir::new().unwrap();
    File::create(buildroot.path().join("pants.toml")).unwrap();

    let config_path_buf = buildroot.path().join("pants.other.toml");
    let config_path = format!("{}", config_path_buf.display());
    File::create(config_path_buf).unwrap();

    // Setting from flag.
    assert_eq!(
        vec!["pants.other.toml"],
        OptionParser::new(
            Args::new(vec![format!("--pants-config-files=['{}']", config_path)]),
            Env { env: btreemap! {} },
            None,
            false,
            false,
            Some(BuildRoot::find_from(buildroot.path()).unwrap()),
            None,
            None,
        )
        .unwrap()
        .get_config_file_paths()
    );

    // Setting to empty and then appending from flags.
    assert_eq!(
        vec!["pants.other.toml"],
        OptionParser::new(
            Args::new(vec![
                "--pants-config-files=[]".to_string(),
                format!("--pants-config-files={}", config_path)
            ]),
            Env { env: btreemap! {} },
            None,
            false,
            false,
            Some(BuildRoot::find_from(buildroot.path()).unwrap()),
            None,
            None,
        )
        .unwrap()
        .get_config_file_paths()
    );

    // Appending from env var.
    assert_eq!(
        vec!["pants.toml", "pants.other.toml"],
        OptionParser::new(
            Args::new([]),
            Env {
                env: btreemap! {"PANTS_CONFIG_FILES".to_string() => config_path.to_string()}
            },
            None,
            false,
            false,
            Some(BuildRoot::find_from(buildroot.path()).unwrap()),
            None,
            None,
        )
        .unwrap()
        .get_config_file_paths()
    );
}

#[test]
fn test_cli_alias() {
    let config = "[cli.alias]\npyupgrade = \"--backend-packages=pants.backend.python.lint.pyupgrade fmt\"\ngreen = \"lint test --force check\"";
    let extra_config = "[cli]\nalias = \"+{'shell': 'repl'}\"";

    with_setup(
        vec!["pyupgrade", "green"],
        vec![],
        config,
        extra_config,
        |option_parser| {
            assert_eq!(
                vec![
                    "fmt".to_string(),
                    "lint".to_string(),
                    "test".to_string(),
                    "check".to_string()
                ],
                option_parser.command.goals
            );
            assert_eq!(
                vec![
                    Flag {
                        context: Scope::Global,
                        key: "--backend-packages".to_string(),
                        value: Some("pants.backend.python.lint.pyupgrade".to_string()),
                    },
                    Flag {
                        context: Scope::Scope("test".to_string()),
                        key: "--force".to_string(),
                        value: None,
                    }
                ],
                option_parser
                    .command
                    .flags
                    .into_iter()
                    .skip(1) // Skip the --config-files flag we add above.
                    .collect::<Vec<_>>(),
            );
        },
    );

    with_setup(
        vec!["shell"],
        vec![],
        config,
        extra_config,
        |option_parser| {
            assert_eq!(vec!["repl".to_string()], option_parser.command.goals);
            assert_eq!(1, option_parser.command.flags.len()); // Just the --config-files flag we add above.
        },
    );
}

#[test]
fn test_cli_alias_validation() {
    let buildroot = TempDir::new().unwrap();
    File::create(buildroot.path().join("BUILDROOT")).unwrap();
    assert_eq!(
        "Invalid alias in `[cli].alias` option: foo. This is already a registered goal or subsytem.",
    OptionParser::new(
        Args::new(vec![]),
        Env {
            env: btreemap!{"PANTS_CLI_ALIAS".to_string() => "{\"foo\": \"fail_on_known_scope\"}".to_string()},
        },
        Some(vec![]),
        false,
        true,
        Some(BuildRoot::find_from(buildroot.path()).unwrap()),
        Some(&hashmap!{"foo".to_string() => hashset!{}}),
        None,
    ).err().unwrap());
}

#[test]
fn test_spec_files() {
    let buildroot = TempDir::new().unwrap();
    File::create(buildroot.path().join("BUILDROOT")).unwrap();
    File::create(buildroot.path().join("extra_specs.txt"))
        .unwrap()
        .write_all("path/to/spec\nanother:spec".as_bytes())
        .unwrap();
    assert_eq!(
        vec![
            "some/initial/spec".to_string(),
            "path/to/spec".to_string(),
            "another:spec".to_string()
        ],
        OptionParser::new(
            Args::new(vec![
                "--spec-files=extra_specs.txt".to_string(),
                "some/initial/spec".to_string()
            ]),
            Env { env: btreemap! {} },
            Some(vec![]),
            false,
            true,
            Some(BuildRoot::find_from(buildroot.path()).unwrap()),
            None,
            None,
        )
        .unwrap()
        .command
        .specs
    );
}

#[test]
fn test_munge_bin_name() {
    let buildroot = BuildRoot::for_path(PathBuf::from("/my/repo"));

    let munge = |input: &str, expected: &str| {
        assert_eq!(
            expected.to_owned(),
            munge_bin_name(input.to_owned(), &buildroot)
        );
    };

    munge("pants", "pants");
    munge("pantsv2", "pantsv2");
    munge("bin/pantsv2", "bin/pantsv2");
    munge("./pants", "./pants");
    munge(buildroot.join("pants").to_str().unwrap(), "./pants");
    munge(
        buildroot.join("bin").join("pants").to_str().unwrap(),
        "./bin/pants",
    );
    munge("/foo/pants", "pants");
    munge("/foo/bar/pants", "pants");
}
