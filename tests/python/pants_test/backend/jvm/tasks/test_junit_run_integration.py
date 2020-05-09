# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import codecs
import os
import time
import xml.etree.ElementTree as ET
from contextlib import contextmanager

from pants.base.build_environment import get_buildroot
from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


class JunitRunIntegrationTest(PantsRunIntegrationTest):
    def _testjvms(self, spec_name):
        spec = f"testprojects/tests/java/org/pantsbuild/testproject/testjvms:{spec_name}"
        self.assert_success(
            self.run_pants(["clean-all", "test.junit", "--strict-jvm-version", spec])
        )

    def test_java_eight(self):
        self._testjvms("eight")

    def test_with_runtime_platform(self):
        self._testjvms("eight-runtime-platform")

    def test_junit_run_against_class_succeeds(self):
        pants_run = self.run_pants(
            [
                "clean-all",
                "test.junit",
                "--test=org.pantsbuild.testproject.matcher.MatcherTest",
                "testprojects/tests/java/org/pantsbuild/testproject/matcher",
            ]
        )
        self.assert_success(pants_run)

    def report_file_path(self, relpath):
        return os.path.join(get_buildroot(), "dist", relpath)

    def cucumber_coverage(self, processor, xml_path, html_path, pre_args=(), tests=(), args=()):
        return self.coverage(
            processor,
            xml_path,
            html_path,
            "testprojects/tests/java/org/pantsbuild/testproject/unicode/cucumber",
            "org.pantsbuild.testproject.unicode.cucumber.CucumberTest",
            pre_args,
            tests,
            args,
        )

    @contextmanager
    def coverage(
        self,
        processor,
        xml_path,
        html_path,
        test_project,
        test_class="",
        pre_args=(),
        tests=(),
        args=(),
    ):
        def test_specifier_arg(test):
            return f"--test={test_class}#{test}"

        with self.pants_results(
            list(pre_args)
            + ["clean-all", "test.junit"]
            + list(args)
            + [test_specifier_arg(name) for name in tests]
            + [
                test_project,
                f"--test-junit-coverage-processor={processor}",
                "--test-junit-coverage",
            ]
        ) as results:
            self.assert_success(results)

            coverage_xml = self.report_file_path(xml_path)
            self.assertTrue(os.path.isfile(coverage_xml))

            coverage_html = self.report_file_path(html_path)
            self.assertTrue(os.path.isfile(coverage_html))

            def read_utf8(path):
                with codecs.open(path, "r", encoding="utf8") as fp:
                    return fp.read()

            yield ET.parse(coverage_xml).getroot(), read_utf8(coverage_html)

    def do_test_junit_run_with_coverage_succeeds_scoverage(self, tests=(), args=()):
        with self.coverage(
            processor="scoverage",
            xml_path="scoverage/reports/xml/scoverage.xml",
            html_path="scoverage/reports/html/org.pantsbuild.example.hello.welcome.html",
            test_project="examples/tests/scala/org/pantsbuild/example/hello/welcome",
            test_class="org.pantsbuild.example.hello.welcome",
            pre_args=["--scoverage-enable-scoverage"],
            tests=tests,
            args=args,
        ) as (xml_report, html_report_string):

            # Validate 100% coverage; ie a line coverage rate of 1.
            self.assertEqual("scoverage", xml_report.tag)
            self.assertEqual(100.0, float(xml_report.attrib["statement-rate"]))

            # Validate that the html report was able to find sources for annotation.
            self.assertIn("WelcomeEverybody", html_report_string)
            self.assertIn("Welcome.scala", html_report_string)

    def test_junit_run_with_coverage_succeeds_scoverage(self):
        self.do_test_junit_run_with_coverage_succeeds_scoverage(args=["--no-chroot"])

    def do_test_junit_run_with_coverage_succeeds_cobertura(self, tests=(), args=()):
        html_path = (
            "test/junit/coverage/reports/html/"
            "org.pantsbuild.testproject.unicode.cucumber.CucumberAnnotatedExample.html"
        )
        with self.cucumber_coverage(
            processor="cobertura",
            xml_path="test/junit/coverage/reports/xml/coverage.xml",
            html_path=html_path,
            tests=tests,
            args=args,
        ) as (xml_report, html_report_string):

            # Validate 100% coverage; ie a line coverage rate of 1.
            self.assertEqual("coverage", xml_report.tag)
            self.assertEqual(1.0, float(xml_report.attrib["line-rate"]))

            # Validate that the html report was able to find sources for annotation.
            self.assertIn("String pleasantry1()", html_report_string)
            self.assertIn("String pleasantry2()", html_report_string)
            self.assertIn("String pleasantry3()", html_report_string)

    def test_junit_run_with_coverage_succeeds_cobertura(self):
        self.do_test_junit_run_with_coverage_succeeds_cobertura()

    def test_junit_run_with_coverage_succeeds_cobertura_merged(self):
        self.do_test_junit_run_with_coverage_succeeds_cobertura(
            tests=["testUnicodeClass1", "testUnicodeClass2", "testUnicodeClass3"],
            args=["--batch-size=2"],
        )

    def do_test_junit_run_with_coverage_succeeds_jacoco(self, tests=(), args=()):
        html_path = (
            "test/junit/coverage/reports/html/"
            "org.pantsbuild.testproject.unicode.cucumber/CucumberAnnotatedExample.html"
        )
        with self.cucumber_coverage(
            processor="jacoco",
            xml_path="test/junit/coverage/reports/xml",
            html_path=html_path,
            tests=tests,
            args=args,
        ) as (xml_report, html_report_string):

            # Validate 100% coverage; ie: 0 missed instructions.
            self.assertEqual("report", xml_report.tag)
            counters = xml_report.findall('counter[@type="INSTRUCTION"]')
            self.assertEqual(1, len(counters))

            total_instruction_counter = counters[0]
            self.assertEqual(0, int(total_instruction_counter.attrib["missed"]))
            self.assertGreater(int(total_instruction_counter.attrib["covered"]), 0)

            # Validate that the html report was able to find sources for annotation.
            self.assertIn('class="el_method">pleasantry1()</a>', html_report_string)
            self.assertIn('class="el_method">pleasantry2()</a>', html_report_string)
            self.assertIn('class="el_method">pleasantry3()</a>', html_report_string)

    def test_junit_run_with_coverage_succeeds_jacoco(self):
        self.do_test_junit_run_with_coverage_succeeds_jacoco()

    def test_junit_run_with_coverage_succeeds_jacoco_merged(self):
        self.do_test_junit_run_with_coverage_succeeds_jacoco(
            tests=["testUnicodeClass1", "testUnicodeClass2", "testUnicodeClass3"],
            args=["--batch-size=2"],
        )

    def test_junit_run_with_coverage_filters_targets_jacoco(self):
        coverage_test_project = "testprojects/tests/java/org/pantsbuild/testproject/coverage"
        html_path = "test/junit/coverage/reports/html/" "index.html"
        filter_arg = "--jacoco-target-filters=one"

        with self.coverage(
            processor="jacoco",
            xml_path="test/junit/coverage/reports/xml",
            html_path=html_path,
            test_project=coverage_test_project,
            args=[filter_arg],
        ) as (xml_report, html_report_string):

            coverage_one = xml_report.find(
                'package/class[@name="org/pantsbuild/testproject/coverage/one/CoverageClassOne"]'
            )
            coverage_two = xml_report.find(
                'package/class[@name="org/pantsbuild/testproject/coverage/two/CoverageClassTwo"]'
            )
            self.assertNotEqual(None, coverage_one)
            self.assertEqual(None, coverage_two)

    def test_junit_run_against_invalid_class_fails(self):
        pants_run = self.run_pants(
            [
                "clean-all",
                "test.junit",
                "--test=org.pantsbuild.testproject.matcher.MatcherTest_BAD_CLASS",
                "testprojects/tests/java/org/pantsbuild/testproject/matcher",
            ]
        )
        self.assert_failure(pants_run)
        self.assertIn("No target found for test specifier", pants_run.stdout_data)

    def test_junit_run_multi(self):
        pants_run = self.run_pants(
            [
                "test.junit",
                "--test=PassingTest",
                "testprojects/tests/java/org/pantsbuild/testproject/dummies:passing_target",
                "testprojects/tests/java/org/pantsbuild/testproject/matcher",
            ]
        )
        self.assert_success(pants_run)
        self.assertIn("OK (2 tests)", pants_run.stdout_data)

    def test_junit_run_timeout_succeeds(self):
        sleeping_target = (
            "testprojects/tests/java/org/pantsbuild/testproject/timeout:sleeping_target"
        )
        pants_run = self.run_pants(
            [
                "clean-all",
                "test.junit",
                "--timeouts",
                "--timeout-default=5",
                "--timeout-terminate-wait=1",
                "--test=org.pantsbuild.testproject.timeout.ShortSleeperTest",
                sleeping_target,
            ]
        )
        self.assert_success(pants_run)

    def test_junit_run_timeout_fails(self):
        sleeping_target = (
            "testprojects/tests/java/org/pantsbuild/testproject/timeout:sleeping_target"
        )
        start = time.time()
        pants_run = self.run_pants(
            [
                "clean-all",
                "test.junit",
                "--timeouts",
                "--timeout-default=5",
                "--timeout-terminate-wait=1",
                "--test=org.pantsbuild.testproject.timeout.LongSleeperTest",
                sleeping_target,
            ]
        )
        end = time.time()
        self.assert_failure(pants_run)

        # Ensure that the failure took less than 120 seconds to run.
        self.assertLess(end - start, 120)

        # Ensure that the timeout triggered.
        self.assertIn(" timed out after 5 seconds", pants_run.stdout_data)

    def test_junit_tests_using_cucumber(self):
        test_spec = "testprojects/tests/java/org/pantsbuild/testproject/cucumber"
        with self.pants_results(
            ["clean-all", "test.junit", "--per-test-timer", test_spec]
        ) as results:
            self.assert_success(results)

    def test_disable_synthetic_jar(self):
        synthetic_jar_target = (
            "testprojects/tests/java/org/pantsbuild/testproject/syntheticjar:test"
        )
        output = self.run_pants(
            ["test.junit", "--output-mode=ALL", synthetic_jar_target]
        ).stdout_data
        self.assertIn("Synthetic jar run is detected", output)

        output = self.run_pants(
            [
                "test.junit",
                "--output-mode=ALL",
                "--no-jvm-synthetic-classpath",
                synthetic_jar_target,
            ]
        ).stdout_data
        self.assertIn("Synthetic jar run is not detected", output)

    def do_test_junit_run_with_html_report(self, tests=(), args=()):
        def html_report_test(test):
            return f"--test=org.pantsbuild.testproject.htmlreport.HtmlReportTest#{test}"

        with self.pants_results(
            ["clean-all", "test.junit"]
            + list(args)
            + [html_report_test(name) for name in tests]
            + [
                "testprojects/tests/java/org/pantsbuild/testproject/htmlreport::",
                "--test-junit-html-report",
            ]
        ) as results:
            self.assert_failure(results)
            report_html = self.report_file_path("test/junit/reports/junit-report.html")
            self.assertTrue(os.path.isfile(report_html))
            with codecs.open(report_html, "r", encoding="utf8") as src:
                html = src.read()
                self.assertIn("testPasses", html)
                self.assertIn("testFails", html)
                self.assertIn("testErrors", html)
                self.assertIn("testSkipped", html)

    def test_junit_run_with_html_report(self):
        self.do_test_junit_run_with_html_report()

    def test_junit_run_with_html_report_merged(self):
        self.do_test_junit_run_with_html_report(
            tests=["testPasses", "testFails", "testErrors", "testSkipped"], args=["--batch-size=3"]
        )
