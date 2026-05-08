// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use crate::parsed_jvm_command_lines::ParsedJVMCommandLines;

// TODO we should be able to use https://docs.rs/crate/derive_builder/0.8.0
#[derive(Debug)]
struct CLIBuilder {
    jdk: Option<String>,
    args_before_classpath: Vec<String>,
    classpath_flag: Option<String>,
    classpath_value: Option<String>,
    args_after_classpath: Vec<String>,
    main_class: Option<String>,
    client_args: Vec<String>,
}

impl CLIBuilder {
    pub fn empty() -> CLIBuilder {
        CLIBuilder {
            jdk: None,
            args_before_classpath: vec![],
            classpath_flag: None,
            classpath_value: None,
            args_after_classpath: vec![],
            main_class: None,
            client_args: vec![],
        }
    }

    pub fn build(&self) -> CLIBuilder {
        CLIBuilder {
            jdk: self.jdk.clone(),
            args_before_classpath: self.args_before_classpath.clone(),
            classpath_flag: self.classpath_flag.clone(),
            classpath_value: self.classpath_value.clone(),
            args_after_classpath: self.args_after_classpath.clone(),
            main_class: self.main_class.clone(),
            client_args: self.client_args.clone(),
        }
    }

    pub fn with_jdk(&mut self) -> &mut CLIBuilder {
        self.jdk = Some(".jdk/bin/java".to_string());
        self
    }

    pub fn with_nailgun_args(&mut self) -> &mut CLIBuilder {
        self.args_before_classpath = vec!["-Xmx4g".to_string()];
        self.args_after_classpath = vec!["-Xmx4g".to_string()];
        self
    }

    pub fn with_classpath(&mut self) -> &mut CLIBuilder {
        self.with_classpath_flag().with_classpath_value()
    }

    pub fn with_classpath_flag(&mut self) -> &mut CLIBuilder {
        self.classpath_flag = Some("-cp".to_string());
        self
    }

    pub fn with_classpath_value(&mut self) -> &mut CLIBuilder {
        self.classpath_value = Some("scala-compiler.jar:scala-library.jar".to_string());
        self
    }

    pub fn with_main_class(&mut self) -> &mut CLIBuilder {
        self.main_class = Some("org.pantsbuild.zinc.compiler.Main".to_string());
        self
    }

    pub fn with_client_args(&mut self) -> &mut CLIBuilder {
        self.client_args = vec!["-some-arg-for-zinc".to_string(), "@argfile".to_string()];
        self
    }

    pub fn with_everything() -> CLIBuilder {
        CLIBuilder::empty()
            .with_jdk()
            .with_nailgun_args()
            .with_classpath()
            .with_main_class()
            .with_client_args()
            .build()
    }

    pub fn render_to_full_cli(&self) -> Vec<String> {
        let mut cli = vec![];
        cli.extend(self.jdk.clone());
        cli.extend(self.args_before_classpath.clone());
        cli.extend(self.classpath_flag.clone());
        cli.extend(self.classpath_value.clone());
        cli.extend(self.args_after_classpath.clone());
        cli.extend(self.main_class.clone());
        cli.extend(self.client_args.clone());
        cli
    }

    pub fn render_to_parsed_args(&self) -> ParsedJVMCommandLines {
        let mut nailgun_args: Vec<String> = self.jdk.iter().cloned().collect();
        nailgun_args.extend(self.args_before_classpath.clone());
        nailgun_args.extend(self.classpath_flag.clone());
        nailgun_args.extend(self.classpath_value.clone());
        nailgun_args.extend(self.args_after_classpath.clone());
        ParsedJVMCommandLines {
            nailgun_args: nailgun_args,
            client_args: self.client_args.clone(),
            client_main_class: self.main_class.clone().unwrap(),
        }
    }
}

#[test]
fn parses_correctly_formatted_cli() {
    let correctly_formatted_cli = CLIBuilder::with_everything();

    let parse_result =
        ParsedJVMCommandLines::parse_command_lines(&correctly_formatted_cli.render_to_full_cli());

    assert_eq!(
        parse_result,
        Ok(correctly_formatted_cli.render_to_parsed_args())
    )
}

#[test]
fn parses_cli_without_jvm_args() {
    let cli_without_jvm_args = CLIBuilder::empty()
        .with_jdk()
        .with_classpath()
        .with_main_class()
        .with_client_args()
        .build();

    let parse_result =
        ParsedJVMCommandLines::parse_command_lines(&cli_without_jvm_args.render_to_full_cli());

    assert_eq!(
        parse_result,
        Ok(cli_without_jvm_args.render_to_parsed_args())
    )
}

#[test]
fn fails_to_parse_cli_without_main_class() {
    let cli_without_main_class = CLIBuilder::empty()
        .with_jdk()
        .with_classpath()
        .with_client_args()
        .build();

    let parse_result =
        ParsedJVMCommandLines::parse_command_lines(&cli_without_main_class.render_to_full_cli());

    assert_eq!(parse_result, Err("No main class provided.".to_string()))
}

#[test]
fn fails_to_parse_cli_without_classpath() {
    let cli_without_classpath = CLIBuilder::empty()
        .with_jdk()
        .with_nailgun_args()
        .with_main_class()
        .with_client_args()
        .build();

    let parse_result =
        ParsedJVMCommandLines::parse_command_lines(&cli_without_classpath.render_to_full_cli());

    assert_eq!(parse_result, Err("No classpath flag found.".to_string()))
}

#[test]
fn fails_to_parse_cli_without_classpath_value() {
    let cli_without_classpath_value = CLIBuilder::empty()
        .with_jdk()
        .with_classpath_flag()
        .with_nailgun_args()
        .with_main_class()
        .build();

    let parse_result = ParsedJVMCommandLines::parse_command_lines(
        &cli_without_classpath_value.render_to_full_cli(),
    );

    assert_eq!(
        parse_result,
        Err("Classpath value has incorrect formatting -Xmx4g.".to_string())
    )
}
