// Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).


package org.pantsbuild.example.annotation.example;

import java.lang.annotation.ElementType;
import java.lang.annotation.Inherited;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/** Annotation indicating the application name */
@Retention(RetentionPolicy.SOURCE)
@Target(ElementType.TYPE)
public @interface Example {
  /** @return A human readable description of the Example */
  String value() default "N/A";
}
