// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
package org.pantsbuild.testproject.coverage;


import org.pantsbuild.testproject.coverage.one.CoverageClassOne;
import org.pantsbuild.testproject.coverage.two.CoverageClassTwo;

import org.junit.Test;
import static org.junit.Assert.assertEquals;

public class CoverAllTest {
    @Test public void coverAllTest() {
        final CoverageClassOne one = new CoverageClassOne(1);
        final CoverageClassTwo two = new CoverageClassTwo(2);
        
        assertEquals(2, one.add(1));
        assertEquals(0, one.sub(1));
        assertEquals(2, one.addIfTrue(true, 1));
        assertEquals(1, one.addIfTrue(false, 1));

        assertEquals(4, two.mult(2));
        assertEquals(1, two.div(2));
        assertEquals(4, two.multIfTrue(true, 2));
        assertEquals(2, two.multIfTrue(false, 2));
    }
}
