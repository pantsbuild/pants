// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.testproject.jarversionincompatibility;

import com.google.common.util.concurrent.RateLimiter;

public class DependsOnRateLimiter {
    public static void main(String[] args) {
        RateLimiter rateLimiter = RateLimiter.create(10000.0); // 10k permits per second
        rateLimiter.acquire();
    }
}
