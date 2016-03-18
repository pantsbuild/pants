// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.junit.impl;

import java.io.File;
import java.io.IOException;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;
import javax.xml.bind.JAXBContext;
import javax.xml.bind.JAXBException;
import javax.xml.bind.Unmarshaller;
import org.hamcrest.CoreMatchers;
import org.junit.After;
import org.junit.Before;
import org.junit.Rule;
import org.junit.rules.TemporaryFolder;
import org.pantsbuild.junit.annotations.TestSerial;

import static org.hamcrest.MatcherAssert.assertThat;
import static org.junit.Assert.fail;

@TestSerial
public class ConsoleRunnerTestHelper {

  @Rule
  public TemporaryFolder temporary = new TemporaryFolder();

  @Before
  public void setUp() {
    ConsoleRunnerImpl.setCallSystemExitOnFinish(false);
    ConsoleRunnerImpl.setExitStatus(0);
    TestRegistry.reset();
  }

  @After
  public void tearDown() {
    ConsoleRunnerImpl.setCallSystemExitOnFinish(true);
    ConsoleRunnerImpl.setExitStatus(0);
  }

  protected void assertContainsTestOutput(String output) {
    assertThat(output, CoreMatchers.containsString("test41"));
    assertThat(output, CoreMatchers.containsString("start test42"));
    assertThat(output, CoreMatchers.containsString("end test42"));
  }

  protected String[] asArgsArray(String cmdLine) {
    String[] args = cmdLine.split(" ");
    for (int i = 0; i < args.length; i++) {
      if (args[i].contains("Test")) {
        args[i] = getClass().getPackage().getName() + '.' + args[i];
      }
    }
    return args;
  }

  protected File runTestAndReturnXmlFile(String testClassName, boolean shouldFail)
      throws IOException, JAXBException {
    String outdirPath = temporary.newFolder("testOutputDir").getAbsolutePath();

    String[] args = new String[] { testClassName, "-outdir", outdirPath, "-xmlreport"};
    if (shouldFail) {
      try {
        ConsoleRunnerImpl.main(args);
        fail("The ConsoleRunner should throw an exception when running these tests");
      } catch (RuntimeException ex) {
        // Expected
      }
    } else {
      ConsoleRunnerImpl.main(args);
    }

    return new File(outdirPath, "TEST-" + testClassName + ".xml");
  }

  protected AntJunitXmlReportListener.TestSuite runTestAndParseXml(
      String testClassName, boolean shouldFail) throws IOException, JAXBException {
    File testXmlFile = runTestAndReturnXmlFile(testClassName, shouldFail);

    JAXBContext jaxbContext = JAXBContext.newInstance(AntJunitXmlReportListener.TestSuite.class);

    Unmarshaller jaxbUnmarshaller = jaxbContext.createUnmarshaller();
    return (AntJunitXmlReportListener.TestSuite) jaxbUnmarshaller.unmarshal(testXmlFile);
  }

  protected void sortTestCasesByName(List<AntJunitXmlReportListener.TestCase> testCases) {
    Collections.sort(testCases, new Comparator<AntJunitXmlReportListener.TestCase>() {
      public int compare(AntJunitXmlReportListener.TestCase tc1,
          AntJunitXmlReportListener.TestCase tc2) {
        return tc1.getName().compareTo(tc2.getName());
      }
    });
  }
}
