// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.cucumber;

import cucumber.api.CucumberOptions;
import cucumber.api.junit.Cucumber;
import org.junit.Test;
import org.junit.runner.RunWith;


@RunWith(Cucumber.class) @CucumberOptions(
    glue = {"org.pantsbuild.testproject.cucumber"})
public class BadnamesTest {
}
