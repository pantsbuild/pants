/*
 * Copyright (c) 2005, 2013, Oracle and/or its affiliates. All rights reserved.
 * DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS FILE HEADER.
 *
 * This code is free software; you can redistribute it and/or modify it
 * under the terms of the GNU General Public License version 2 only, as
 * published by the Free Software Foundation.  Oracle designates this
 * particular file as subject to the "Classpath" exception as provided
 * by Oracle in the LICENSE file that accompanied this code.
 *
 * This code is distributed in the hope that it will be useful, but WITHOUT
 * ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
 * FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
 * version 2 for more details (a copy is included in the LICENSE file that
 * accompanied this code).
 *
 * You should have received a copy of the GNU General Public License version
 * 2 along with this work; if not, write to the Free Software Foundation,
 * Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301 USA.
 *
 * Please contact Oracle, 500 Oracle Parkway, Redwood Shores, CA 94065 USA
 * or visit www.oracle.com if you need additional information or have any
 * questions.
 */

// This file is a dummy version of the standard JavacTool, for use when testing Pants' ability
// to run custom javac versions.
//
// Background:  Zinc can either fork a separate javac process, or run one in-process.
// Pants uses Zinc in the latter mode.  In this mode, Zinc by default delegates to
// javax.tools.ToolProvider.getSystemJavaCompiler.  That method, in turn, attempts to load a class
// called com.sun.tools.javac.api.JavacTool.
//
// This dummy version of that class allows us to test our ability to provide a custom javac
// outside the one embedded in the JDK we run Zinc with.
//
// Note that the real version of this class is in the JDK 8 source code here:
// http://hg.openjdk.java.net/jdk8/jdk8/langtools/file/ \
// 1ff9d5118aae/src/share/classes/com/sun/tools/javac/api/JavacTool.java.
//
// As the comments in that file state: This is NOT part of any supported API.  So in the future we
// may need to modify this file and/or keep multiple versions of it, to support multiple Java
// runtime versions.
//
// License Note:
// =============
// This class is a dummy version of a class in a file covered by Oracle's "Classpath" exception
// to GPLv2.  The only thing it shares with the real class is its name.  Nonetheless, to ensure
// that even this tiny "borrowing" is in compliance with the original file's license, we:
//
// A) Reproduce the original license notice above, and extend it to this file.
// B) Assert our right to extend the "Classpath" exception to this modified version.
//
// This means that we are permitted to link this library with independent modules to produce
// a binary, and we may distribute that binary under license terms of our choice
// (specifically, the Apache License, Version 2.0, which is otherwise incompatible with GPLv2).
// See http://openjdk.java.net/legal/gplv2+ce.html.
//
// TODO: Run this by someone who truly understands software licensing rules.  Maybe this abundance
// of caution is unnecessary, and we can just re-use the name with no license considerations.

package com.sun.tools.javac.api;

import javax.lang.model.SourceVersion;
import javax.tools.*;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.Writer;
import java.nio.charset.Charset;
import java.util.Locale;
import java.util.Set;


public final class JavacTool implements JavaCompiler {
  private RuntimeException identifyMe() {
    return new RuntimeException("Pants caused Zinc to load a custom JavacTool");
  }

  @Override
  public CompilationTask getTask(Writer out, JavaFileManager fileManager,
                                 DiagnosticListener<? super JavaFileObject> diagnosticListener,
                                 Iterable<String> options, Iterable<String> classes,
                                 Iterable<? extends JavaFileObject> compilationUnits) {
    throw identifyMe();
  }

  @Override
  public StandardJavaFileManager getStandardFileManager(
      DiagnosticListener<? super JavaFileObject> diagnosticListener,
      Locale locale,
      Charset charset) {
    throw identifyMe();
  }

  @Override
  public int isSupportedOption(String option) {
    throw identifyMe();
  }

  @Override
  public int run(InputStream in, OutputStream out, OutputStream err, String... arguments) {
    throw identifyMe();
  }

  @Override
  public Set<SourceVersion> getSourceVersions() {
    throw identifyMe();
  }
}
