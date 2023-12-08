# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import textwrap
from textwrap import dedent
from typing import Iterable

import pytest

from internal_plugins.test_lockfile_fixtures.lockfile_fixture import (
    JVMLockfileFixture,
    JVMLockfileFixtureDefinition,
)
from pants.backend.codegen.soap.java.jaxws import JaxWsTools
from pants.backend.codegen.soap.java.rules import GenerateJavaFromWsdlRequest
from pants.backend.codegen.soap.java.rules import rules as java_wsdl_rules
from pants.backend.codegen.soap.rules import rules as wsdl_rules
from pants.backend.codegen.soap.target_types import WsdlSourceField, WsdlSourcesGeneratorTarget
from pants.backend.experimental.java.register import rules as java_backend_rules
from pants.backend.java.compile.javac import CompileJavaSourceRequest
from pants.backend.java.target_types import JavaSourcesGeneratorTarget, JavaSourceTarget
from pants.build_graph.address import Address
from pants.core.util_rules import config_files, source_files, stripped_source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine import process
from pants.engine.internals import graph
from pants.engine.rules import QueryRule
from pants.engine.target import GeneratedSources, HydratedSources, HydrateSourcesRequest
from pants.jvm import classpath, testutil
from pants.jvm.compile import rules as jvm_compile_rules
from pants.jvm.jdk_rules import rules as jdk_rules
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.target_types import JvmArtifactTarget
from pants.jvm.testutil import (
    RenderedClasspath,
    expect_single_expanded_coarsened_target,
    make_resolve,
)
from pants.jvm.util_rules import rules as jdk_util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner


@pytest.fixture
def wsdl_lockfile_def() -> JVMLockfileFixtureDefinition:
    return JVMLockfileFixtureDefinition(
        "wdsl.test.lock",
        ["com.sun.xml.ws:jaxws-rt:2.3.5"],
    )


@pytest.fixture
def wsdl_lockfile(wsdl_lockfile_def: JVMLockfileFixtureDefinition, request) -> JVMLockfileFixture:
    return wsdl_lockfile_def.load(request)


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *java_backend_rules(),
            *config_files.rules(),
            *classpath.rules(),
            *coursier_fetch_rules(),
            *coursier_setup_rules(),
            *external_tool_rules(),
            *graph.rules(),
            *jdk_rules(),
            *jdk_util_rules(),
            *jvm_compile_rules(),
            *process.rules(),
            *source_files.rules(),
            *stripped_source_files.rules(),
            *java_wsdl_rules(),
            *wsdl_rules(),
            *testutil.rules(),
            QueryRule(JaxWsTools, ()),
            QueryRule(HydratedSources, [HydrateSourcesRequest]),
            QueryRule(GeneratedSources, [GenerateJavaFromWsdlRequest]),
            QueryRule(RenderedClasspath, (CompileJavaSourceRequest,)),
        ],
        target_types=[
            JavaSourceTarget,
            JavaSourcesGeneratorTarget,
            JvmArtifactTarget,
            WsdlSourcesGeneratorTarget,
        ],
    )
    rule_runner.set_options([], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


def assert_files_generated(
    rule_runner: RuleRunner,
    address: Address,
    *,
    expected_files: list[str],
    source_roots: list[str],
    extra_args: Iterable[str] = (),
) -> None:
    args = [f"--source-root-patterns={repr(source_roots)}", *extra_args]
    rule_runner.set_options(args, env_inherit=PYTHON_BOOTSTRAP_ENV)
    tgt = rule_runner.get_target(address)
    protocol_sources = rule_runner.request(
        HydratedSources, [HydrateSourcesRequest(tgt[WsdlSourceField])]
    )
    generated_sources = rule_runner.request(
        GeneratedSources, [GenerateJavaFromWsdlRequest(protocol_sources.snapshot, tgt)]
    )
    assert set(generated_sources.snapshot.files) == set(expected_files)


_FOO_SERVICE_WSDL = dedent(
    """\
  <?xml version="1.0" encoding="UTF-8"?>
  <wsdl:definitions name="FooService"
      targetNamespace="http://www.example.com/wsdl/FooService"
      xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/"
      xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/"
      xmlns:tns="http://www.example.com/wsdl/FooService"
      xmlns:xsd="http://www.w3.org/2001/XMLSchema">

    <wsdl:types />

    <wsdl:message name="FooRequest">
      <wsdl:part name="arg0" type="xsd:int" />
    </wsdl:message>

    <wsdl:message name="FooResponse">
      <wsdl:part name="ret0" type="xsd:boolean" />
    </wsdl:message>

    <wsdl:portType name="FooPortType">
      <wsdl:operation name="doSomething">
        <wsdl:input message="tns:FooRequest" />
        <wsdl:output message="tns:FooResponse" />
      </wsdl:operation>
    </wsdl:portType>

    <wsdl:binding name="FooBinding" type="tns:FooPortType">
      <soap:binding transport="http://schemas.xmlsoap.org/soap/http" style="rpc"/>
      <wsdl:operation name="doSomething">
        <soap:operation soapAction="" />
        <wsdl:input>
          <soap:body use="literal" namespace="http://www.example.com/wsdl/FooService" />
        </wsdl:input>
        <wsdl:output>
          <soap:body use="literal" namespace="http://www.example.com/wsdl/FooService" />
        </wsdl:output>
      </wsdl:operation>
    </wsdl:binding>

    <wsdl:service name="FooService">
      <wsdl:port name="FooPort" binding="tns:FooBinding">
        <soap:address location="http://www.example.com/FooService" />
      </wsdl:port>
    </wsdl:service>
  </wsdl:definitions>
  """
)


def test_generate_java_from_wsdl(
    rule_runner: RuleRunner, wsdl_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "src/wsdl/BUILD": "wsdl_sources()",
            "src/wsdl/FooService.wsdl": _FOO_SERVICE_WSDL,
            "3rdparty/jvm/default.lock": wsdl_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": wsdl_lockfile.requirements_as_jvm_artifact_targets(),
            "src/jvm/BUILD": "java_sources(dependencies=['src/wsdl'])",
            "src/jvm/FooServiceMain.java": textwrap.dedent(
                """\
                package org.pantsbuild.example;
                import com.example.wsdl.fooservice.FooService;
                public class FooServiceMain {
                    public static void main(String[] args) {
                        FooService service = new FooService();
                    }
                }
                """
            ),
        }
    )

    def assert_gen(addr: Address, expected: Iterable[str]) -> None:
        assert_files_generated(
            rule_runner, addr, source_roots=["src/wsdl"], expected_files=list(expected)
        )

    assert_gen(
        Address("src/wsdl", relative_file_path="FooService.wsdl"),
        (
            "src/wsdl/com/example/wsdl/fooservice/FooPortType.java",
            "src/wsdl/com/example/wsdl/fooservice/FooService.java",
        ),
    )

    request = CompileJavaSourceRequest(
        component=expect_single_expanded_coarsened_target(
            rule_runner, Address(spec_path="src/jvm")
        ),
        resolve=make_resolve(rule_runner),
    )
    _ = rule_runner.request(RenderedClasspath, [request])


def test_generate_java_module_from_wsdl(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/wsdl/BUILD": "wsdl_sources(java_module='foo')",
            "src/wsdl/FooService.wsdl": _FOO_SERVICE_WSDL,
        }
    )

    def assert_gen(addr: Address, expected: Iterable[str]) -> None:
        assert_files_generated(
            rule_runner, addr, source_roots=["src/wsdl"], expected_files=list(expected)
        )

    assert_gen(
        Address("src/wsdl", relative_file_path="FooService.wsdl"),
        (
            "src/wsdl/com/example/wsdl/fooservice/FooPortType.java",
            "src/wsdl/com/example/wsdl/fooservice/FooService.java",
            "src/wsdl/module-info.java",
        ),
    )


def test_generate_java_from_wsdl_using_custom_package(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/wsdl/BUILD": "wsdl_sources(java_package='fooservice')",
            "src/wsdl/FooService.wsdl": _FOO_SERVICE_WSDL,
        }
    )

    def assert_gen(addr: Address, expected: Iterable[str]) -> None:
        assert_files_generated(
            rule_runner, addr, source_roots=["src/wsdl"], expected_files=list(expected)
        )

    assert_gen(
        Address("src/wsdl", relative_file_path="FooService.wsdl"),
        (
            "src/wsdl/fooservice/FooPortType.java",
            "src/wsdl/fooservice/FooService.java",
        ),
    )


def test_generate_java_from_wsdl_with_embedded_xsd(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/wsdl/dir1/BUILD": "wsdl_sources()",
            "src/wsdl/dir1/HelloService.wsdl": dedent(
                """\
                <?xml version="1.0" encoding="UTF-8"?>
                <wsdl:definitions name="HelloService"
                    targetNamespace="http://www.example.com/wsdl/HelloService/"
                    xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/"
                    xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/"
                    xmlns:tns="http://www.example.com/wsdl/HelloService/"
                    xmlns:xsd="http://www.w3.org/2001/XMLSchema">

                  <wsdl:types>
                    <xsd:schema targetNamespace="http://www.example.com/wsdl/HelloService/">
                      <xsd:element name="Greeter" type="tns:Greeter" />
                      <xsd:complexType name="Greeter">
                        <xsd:sequence>
                          <xsd:element name="name" type="xsd:string" />
                        </xsd:sequence>
                      </xsd:complexType>

                      <xsd:element name="Greeting" type="tns:Greeting" />
                      <xsd:complexType name="Greeting">
                        <xsd:sequence>
                          <xsd:element name="message" type="xsd:string" />
                        </xsd:sequence>
                      </xsd:complexType>
                    </xsd:schema>
                  </wsdl:types>

                  <wsdl:message name="SayHelloRequest">
                    <wsdl:part name="greeter" type="tns:Greeter" />
                  </wsdl:message>

                  <wsdl:message name="SayHelloResponse">
                     <wsdl:part name="greeting" type="tns:Greeting" />
                  </wsdl:message>

                  <wsdl:portType name="HelloPortType">
                     <wsdl:operation name="sayHello">
                        <wsdl:input message="tns:SayHelloRequest" />
                        <wsdl:output message="tns:SayHelloResponse" />
                     </wsdl:operation>
                  </wsdl:portType>

                  <wsdl:binding name="HelloBinding" type="tns:HelloPortType">
                     <soap:binding transport="http://schemas.xmlsoap.org/soap/http" style="rpc"/>
                     <wsdl:operation name="sayHello">
                        <soap:operation soapAction="http://www.example.com/wsdl/HelloService/sayHello" />
                        <wsdl:input>
                           <soap:body use="literal" namespace="http://www.example.com/wsdl/HelloService/" />
                        </wsdl:input>

                        <wsdl:output>
                           <soap:body use="literal" namespace="http://www.example.com/wsdl/HelloService/" />
                        </wsdl:output>
                     </wsdl:operation>
                  </wsdl:binding>

                  <wsdl:service name="HelloService">
                     <wsdl:documentation>WSDL File for HelloService</wsdl:documentation>

                     <wsdl:port name="HelloPort" binding="tns:HelloBinding">
                        <soap:address location="http://www.example.com/HelloService" />
                     </wsdl:port>
                  </wsdl:service>
                </wsdl:definitions>
                """
            ),
        }
    )

    def assert_gen(addr: Address, expected: Iterable[str]) -> None:
        assert_files_generated(
            rule_runner, addr, source_roots=["src/wsdl"], expected_files=list(expected)
        )

    assert_gen(
        Address("src/wsdl/dir1", relative_file_path="HelloService.wsdl"),
        (
            "src/wsdl/com/example/wsdl/helloservice/Greeter.java",
            "src/wsdl/com/example/wsdl/helloservice/Greeting.java",
            "src/wsdl/com/example/wsdl/helloservice/HelloPortType.java",
            "src/wsdl/com/example/wsdl/helloservice/HelloService.java",
            "src/wsdl/com/example/wsdl/helloservice/ObjectFactory.java",
            "src/wsdl/com/example/wsdl/helloservice/package-info.java",
        ),
    )
