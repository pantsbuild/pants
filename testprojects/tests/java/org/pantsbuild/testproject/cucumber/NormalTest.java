// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.cucumber;

import org.junit.Test;
import static org.junit.Assert.assertEquals;

public class NormalTest {
    @Test public void normalTest() {
        assertEquals("NormalTest", getClass().getSimpleName());
    }
}
