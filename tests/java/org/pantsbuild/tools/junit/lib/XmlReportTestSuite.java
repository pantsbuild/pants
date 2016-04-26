package org.pantsbuild.tools.junit.lib;

import org.junit.runner.RunWith;
import org.junit.runners.Suite;

/**
 * This test is intentionally under a java_library() BUILD target so it will not be run
 * on its own. It is run by the ConsoleRunnerTest suite to test ConsoleRunnerImpl.
 */
@RunWith(Suite.class)
@Suite.SuiteClasses({
    XmlReportAllPassingTest.class,
    XmlReportTest.class
})
public class XmlReportTestSuite {
}
