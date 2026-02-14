// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use maplit::hashmap;
use options::Scope;

use crate::pants_invocation::{Args, Command, Flag, PantsInvocation, SubCommand};

fn mk_flag(key: &str, value: Option<&str>) -> Flag {
    Flag {
        key: key.to_string(),
        value: value.map(str::to_string),
    }
}

fn mk_subcommand(name: &str, flags: Vec<Flag>) -> SubCommand {
    SubCommand {
        name: name.to_string(),
        flags,
    }
}

fn mk_command(name: &str, flags: Vec<Flag>, subcommand: Option<SubCommand>) -> Command {
    Command {
        name: name.to_string(),
        flags,
        subcommand,
    }
}

fn mk_invocation(args_str: &str) -> Result<PantsInvocation, String> {
    // Note that for readability the cmd lines in the test include the arg[0] binary name,
    // which we skip here.
    let args = Args::new(
        shlex::split(args_str)
            .unwrap()
            .into_iter()
            .skip(1)
            .collect::<Vec<_>>(),
    );
    PantsInvocation::from_args(args)
}

fn assert_error(args_str: &str, expected_err: &str) {
    let pi = mk_invocation(args_str);
    assert!(pi.is_err());
    assert_eq!(pi.unwrap_err(), expected_err);
}

#[test]
fn test_no_command() {
    assert_eq!(
        mk_invocation("pants").unwrap(),
        PantsInvocation {
            global_flags: vec![],
            commands: vec![],
            specs: vec![],
            passthru: None
        },
    );

    assert_eq!(
        mk_invocation("pants --foo").unwrap(),
        PantsInvocation {
            global_flags: vec![mk_flag("foo", None),],
            commands: vec![],
            specs: vec![],
            passthru: None,
        },
    );

    assert_eq!(
        mk_invocation("pants --bar=baz").unwrap(),
        PantsInvocation {
            global_flags: vec![mk_flag("bar", Some("baz")),],
            commands: vec![],
            specs: vec![],
            passthru: None,
        },
    );

    assert_eq!(
        mk_invocation("pants --foo --bar=baz").unwrap(),
        PantsInvocation {
            global_flags: vec![mk_flag("foo", None), mk_flag("bar", Some("baz")),],
            commands: vec![],
            specs: vec![],
            passthru: None,
        },
    );

    assert_eq!(
        mk_invocation("pants --bar=baz --foo --bar=qux").unwrap(),
        PantsInvocation {
            global_flags: vec![
                mk_flag("bar", Some("baz")),
                mk_flag("foo", None),
                mk_flag("bar", Some("qux")),
            ],
            commands: vec![],
            specs: vec![],
            passthru: None,
        },
    );
}

#[test]
fn test_command_no_subcommand() {
    assert_eq!(
        mk_invocation("pants --foo --bar=baz cmd").unwrap(),
        PantsInvocation {
            global_flags: vec![mk_flag("foo", None), mk_flag("bar", Some("baz")),],
            commands: vec![mk_command("cmd", vec![], None)],
            specs: vec![],
            passthru: None,
        },
    );

    assert_eq!(
        mk_invocation("pants --foo cmd --bar=baz").unwrap(),
        PantsInvocation {
            global_flags: vec![mk_flag("foo", None),],
            commands: vec![mk_command("cmd", vec![mk_flag("bar", Some("baz"))], None)],
            specs: vec![],
            passthru: None,
        },
    );

    assert_eq!(
        mk_invocation("pants --foo cmd --bar=baz path/to/file").unwrap(),
        PantsInvocation {
            global_flags: vec![mk_flag("foo", None),],
            commands: vec![mk_command("cmd", vec![mk_flag("bar", Some("baz"))], None)],
            specs: vec!["path/to/file".to_string()],
            passthru: None,
        },
    );

    assert_eq!(
        mk_invocation("pants --foo cmd --bar=baz path/to/file1 path/to/file2").unwrap(),
        PantsInvocation {
            global_flags: vec![mk_flag("foo", None),],
            commands: vec![mk_command("cmd", vec![mk_flag("bar", Some("baz"))], None)],
            specs: vec!["path/to/file1".to_string(), "path/to/file2".to_string()],
            passthru: None,
        },
    );

    assert_eq!(
        mk_invocation("pants --foo cmd --bar=baz -- passthru_arg --passthru-flag").unwrap(),
        PantsInvocation {
            global_flags: vec![mk_flag("foo", None),],
            commands: vec![mk_command("cmd", vec![mk_flag("bar", Some("baz"))], None)],
            specs: vec![],
            passthru: Some(vec![
                "passthru_arg".to_string(),
                "--passthru-flag".to_string()
            ]),
        },
    );

    assert_eq!(
        mk_invocation("pants --foo cmd --bar=baz path/to/file -- passthru_arg --passthru-flag")
            .unwrap(),
        PantsInvocation {
            global_flags: vec![mk_flag("foo", None),],
            commands: vec![mk_command("cmd", vec![mk_flag("bar", Some("baz"))], None)],
            specs: vec!["path/to/file".to_string()],
            passthru: Some(vec![
                "passthru_arg".to_string(),
                "--passthru-flag".to_string()
            ]),
        },
    );
}

#[test]
fn test_valid_command_name() {
    assert_eq!(
        mk_invocation("pants foo").unwrap(),
        PantsInvocation {
            global_flags: vec![],
            commands: vec![mk_command("foo", vec![], None,)],
            specs: vec![],
            passthru: None,
        },
    );

    assert_eq!(
        mk_invocation("pants foo-bar").unwrap(),
        PantsInvocation {
            global_flags: vec![],
            commands: vec![mk_command("foo-bar", vec![], None,)],
            specs: vec![],
            passthru: None,
        },
    );

    assert_eq!(
        mk_invocation("pants foo2").unwrap(),
        PantsInvocation {
            global_flags: vec![],
            commands: vec![mk_command("foo2", vec![], None,)],
            specs: vec![],
            passthru: None,
        },
    );

    assert_eq!(
        mk_invocation("pants foo2-bar").unwrap(),
        PantsInvocation {
            global_flags: vec![],
            commands: vec![mk_command("foo2-bar", vec![], None,)],
            specs: vec![],
            passthru: None,
        },
    );
}

#[test]
fn test_command_and_subcommand() {
    assert_eq!(
        mk_invocation("pants --foo --bar=baz cmd subcmd").unwrap(),
        PantsInvocation {
            global_flags: vec![mk_flag("foo", None), mk_flag("bar", Some("baz")),],
            commands: vec![mk_command(
                "cmd",
                vec![],
                Some(mk_subcommand("subcmd", vec![]))
            )],
            specs: vec![],
            passthru: None,
        },
    );

    assert_eq!(
        mk_invocation("pants --foo cmd --bar=baz subcmd").unwrap(),
        PantsInvocation {
            global_flags: vec![mk_flag("foo", None),],
            commands: vec![mk_command(
                "cmd",
                vec![mk_flag("bar", Some("baz")),],
                Some(mk_subcommand("subcmd", vec![]))
            )],
            specs: vec![],
            passthru: None,
        },
    );

    assert_eq!(
        mk_invocation("pants --foo cmd --bar=baz subcmd --qux=quux").unwrap(),
        PantsInvocation {
            global_flags: vec![mk_flag("foo", None),],
            commands: vec![mk_command(
                "cmd",
                vec![mk_flag("bar", Some("baz")),],
                Some(mk_subcommand("subcmd", vec![mk_flag("qux", Some("quux"))]))
            )],
            specs: vec![],
            passthru: None,
        },
    );

    assert_eq!(
        mk_invocation("pants --foo cmd --bar=baz subcmd --qux=quux path/to/file1 ./path2").unwrap(),
        PantsInvocation {
            global_flags: vec![mk_flag("foo", None),],
            commands: vec![mk_command(
                "cmd",
                vec![mk_flag("bar", Some("baz")),],
                Some(mk_subcommand("subcmd", vec![mk_flag("qux", Some("quux"))]))
            )],
            specs: vec!["path/to/file1".to_string(), "./path2".to_string()],
            passthru: None,
        },
    );

    assert_eq!(
        mk_invocation("pants --foo cmd --bar=baz subcmd --qux=quux path/to/file1 ./path2 --global-flag-after-specs=val").unwrap(),
        PantsInvocation {
            global_flags: vec![mk_flag("foo", None), mk_flag("global-flag-after-specs", Some("val")),],
            commands: vec![mk_command(
                "cmd",
                vec![mk_flag("bar", Some("baz")),],
                Some(mk_subcommand("subcmd", vec![mk_flag("qux", Some("quux"))]))
            )],
            specs: vec!["path/to/file1".to_string(), "./path2".to_string()],
            passthru: None,
        },
    );

    assert_eq!(
        mk_invocation("pants --foo cmd --bar=baz subcmd --qux=quux path/to/file1 ./path2 --global-flag-after-specs -- passthru_arg --passthru-flag").unwrap(),
        PantsInvocation {
            global_flags: vec![mk_flag("foo", None), mk_flag("global-flag-after-specs", None),],
            commands: vec![mk_command(
                "cmd",
                vec![mk_flag("bar", Some("baz")),],
                Some(mk_subcommand("subcmd", vec![mk_flag("qux", Some("quux"))]))
            )],
            specs: vec!["path/to/file1".to_string(), "./path2".to_string()],
            passthru: Some(vec![
                "passthru_arg".to_string(),
                "--passthru-flag".to_string()
            ]),
        },
    );
}

#[test]
fn test_multiple_commands_and_subcommands() {
    assert_eq!(
        mk_invocation("pants cmd1 subcmd1 + cmd2 + cmd3 subcmd3").unwrap(),
        PantsInvocation {
            global_flags: vec![],
            commands: vec![
                mk_command("cmd1", vec![], Some(mk_subcommand("subcmd1", vec![]))),
                mk_command("cmd2", vec![], None,),
                mk_command("cmd3", vec![], Some(mk_subcommand("subcmd3", vec![])))
            ],
            specs: vec![],
            passthru: None,
        },
    );

    assert_eq!(
        mk_invocation("pants --global-flag cmd1 --cmd1-flag subcmd1 --subcmd1-flag + cmd2 --cmd2-flag + cmd3 --cmd3-flag subcmd3 --subcmd3-flag path/to/spec --another-global-flag -- passthru").unwrap(),
        PantsInvocation {
            global_flags: vec![mk_flag("global-flag", None), mk_flag("another-global-flag", None),],
            commands: vec![mk_command(
                "cmd1",
                vec![mk_flag("cmd1-flag", None)],
                Some(mk_subcommand("subcmd1", vec![mk_flag("subcmd1-flag", None)]))
            ), mk_command(
                "cmd2",
                vec![mk_flag("cmd2-flag", None)],
                None,
            ), mk_command(
                "cmd3",
                vec![mk_flag("cmd3-flag", None)],
                Some(mk_subcommand("subcmd3", vec![mk_flag("subcmd3-flag", None)]))
            )],
            specs: vec!["path/to/spec".to_string()],
            passthru: Some(vec!["passthru".to_string()]),
        },
    );
}

#[test]
fn test_errors() {
    assert_error(
        "pants cmd _bad_cmd_name",
        "Invalid command name `_bad_cmd_name`",
    );

    assert_error(
        "pants cmd 0bad_cmd_name",
        "Invalid command name `0bad_cmd_name`",
    );

    assert_error(
        "pants path/to/spec",
        "Path specs must come after commands, but found `path/to/spec` before any commands",
    );

    assert_error(
        "pants path/to/spec1 path/to/spec2 cmd",
        "Path specs must come after commands, but found `path/to/spec1 path/to/spec2` before any commands",
    );

    assert_error(
        "pants path/to/spec1 cmd path/to/spec2",
        "Path specs must come after commands, but found `path/to/spec1` before any commands",
    );

    assert_error(
        "pants cmd subcmd path/to/spec subcmd2",
        "Extraneous argument `subcmd2`",
    );
}

#[test]
fn test_get_flags() {
    let flags = mk_invocation(
        "pants --global_flag1 --scope-scoped_flag1=foo --global_flag2=false --scope-scoped_flag1=bar cmd1 --cmd1_flag + cmd2 --cmd2_flag=true subcmd --subcmd_flag=42"
    ).unwrap().get_flags();

    assert_eq!(
        flags,
        hashmap! {
            Scope::Global => hashmap! {
                "global_flag1".to_string() => vec![None],
                "global_flag2".to_string() => vec![Some("false".to_string())],
            },
            Scope::named("scope") => hashmap! {
                "scoped_flag1".to_string() => vec![Some("foo".to_string()), Some("bar".to_string())],
            },
            Scope::named("cmd1") => hashmap! {
                "cmd1_flag".to_string() => vec![None],
            },
            Scope::named("cmd2") => hashmap! {
                "cmd2_flag".to_string() => vec![Some("true".to_string())],
            },
            Scope::named("cmd2.subcmd") => hashmap! {
                "subcmd_flag".to_string() => vec![Some("42".to_string())],
            },
        }
    );
}
