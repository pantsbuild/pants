# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Iterable

import pytest
from pants.backend.java.target_types import JavaSourcesGeneratorTarget, JavaSourceTarget
from pants.build_graph.address import Address
from pants.core.util_rules import config_files, source_files, stripped_source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine import process
from pants.engine.internals import graph
from pants.engine.rules import QueryRule
from pants.engine.target import GeneratedSources, HydratedSources, HydrateSourcesRequest
from pants.jvm import classpath
from pants.jvm.compile import rules as jvm_compile_rules
from pants.jvm.jdk_rules import rules as jdk_rules
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.util_rules import rules as jdk_util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner

from pants.backend.codegen.wsdl.java.jaxws import JaxWsTools
from pants.backend.codegen.wsdl.java.rules import GenerateJavaFromWsdlRequest
from pants.backend.codegen.wsdl.java.rules import rules as java_wsdl_rules
from pants.backend.codegen.wsdl.rules import rules as wsdl_rules
from pants.backend.codegen.wsdl.target_types import WsdlSourceField, WsdlSourcesGeneratorTarget


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
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
            # Rules under test
            *java_wsdl_rules(),
            *wsdl_rules(),
            # Queries to support the tests
            QueryRule(JaxWsTools, ()),
            QueryRule(HydratedSources, [HydrateSourcesRequest]),
            QueryRule(GeneratedSources, [GenerateJavaFromWsdlRequest]),
        ],
        target_types=[JavaSourceTarget, JavaSourcesGeneratorTarget, WsdlSourcesGeneratorTarget],
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


def test_generate_java_from_wsdl(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/wsdl/dir1/BUILD": "wsdl_sources()",
            "src/wsdl/dir1/HelloService.wsdl": dedent(
                """\
                <?xml version="1.0" encoding="UTF-8"?>
                <wsdl:definitions name="HelloService"
                    targetNamespace="http://www.examples.com/wsdl/HelloService/"
                    xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/"
                    xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/"
                    xmlns:tns="http://www.examples.com/wsdl/HelloService/"
                    xmlns:xsd="http://www.w3.org/2001/XMLSchema">

                  <wsdl:types>
                    <xsd:schema targetNamespace="http://www.examples.com/wsdl/HelloService/">
                      <xsd:element name="Greeter">
                        <xsd:complexType>
                          <xsd:sequence>
                            <xsd:element name="name" type="xsd:string" />
                          </xsd:sequence>
                        </xsd:complexType>
                      </xsd:element>

                      <xsd:element name="Greeting">
                        <xsd:complexType>
                          <xsd:sequence>
                            <xsd:element name="message" type="xsd:string" />
                          </xsd:sequence>
                        </xsd:complexType>
                      </xsd:element>
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
                     <soap:binding transport="http://schemas.xmlsoap.org/soap/http"/>
                     <wsdl:operation name="sayHello">
                        <soap:operation soapAction="http://www.examples.com/wsdl/HelloService/sayHello" />
                        <wsdl:input>
                           <soap:body use="literal" namespace="http://www.examples.com/wsdl/HelloService/" />
                        </wsdl:input>

                        <wsdl:output>
                           <soap:body use="literal" namespace="http://www.examples.com/wsdl/HelloService/" />
                        </wsdl:output>
                     </wsdl:operation>
                  </wsdl:binding>

                  <wsdl:service name="HelloService">
                     <wsdl:documentation>WSDL File for HelloService</wsdl:documentation>

                     <wsdl:port name="HelloPort" binding="tns:HelloBinding">
                        <soap:address location="http://www.examples.com/HelloService/" />
                     </wsdl:port>
                  </wsdl:service>
                </wsdl:definitions>
                """
            ),
        }
    )

    def assert_gen(addr: Address, expected: Iterable[str]) -> None:
        assert_files_generated(
            rule_runner, addr, source_roots=["src/java", "src/wsdl"], expected_files=list(expected)
        )

    assert_gen(
        Address("src/wsdl/dir1", relative_file_path="HelloService.wsdl"),
        (
            "src/wsdl/com/examples/wsdl/helloservice/Greeter.java",
            "src/wsdl/com/examples/wsdl/helloservice/Greeting.java",
            "src/wsdl/com/examples/wsdl/helloservice/ObjectFactory.java",
            "src/wsdl/com/examples/wsdl/helloservice/package-info.java",
        ),
    )
