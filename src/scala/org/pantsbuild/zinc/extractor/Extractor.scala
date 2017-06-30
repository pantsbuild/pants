/**
 * Copyright (C) 2017 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

package org.pantsbuild.zinc.extractor

import java.io.File

import sbt.internal.inc.{Analysis, FileBasedStore, Locate}

import xsbti.compile.CompileAnalysis

import org.pantsbuild.zinc.analysis.AnalysisMap

/**
 * Class to encapsulate extracting information from zinc analysis.
 */
class Extractor(
  classpath: Seq[File],
  analysis: CompileAnalysis,
  analysisMap: AnalysisMap
) {
  private val relations = analysis.asInstanceOf[Analysis].relations

  // A lookup from classname to defining classpath entry File.
  private val definesClass = Locate.entry(classpath, analysisMap.getPCELookup)

  /**
   * Extract a mapping from source file to produced classfiles.
   */
  def products: Map[File, Set[File]] =
    relations
      .allSources
      .toSeq
      .map { source =>
        source -> relations.products(source)
      }
      .toMap

  /**
   * Extract all file or classname dependencies of this compilation unit that can be
   * determined from analysis.
   *
   * TODO: In future, this could use the analysis for the relevant dependencies of the
   * module to walk through classnames to actual file deps.
   */
  def dependencies: Set[File] = {
    val external =
      relations
        .allExternalDeps
        .flatMap { classname =>
          definesClass(classname).orElse {
            // This case should be rare: should only occur when a compiler plugin generates
            // additional classes.
            System.err.println(s"No analysis declares class $classname")
            None
          }
        }
        .toSet

    val library =
      relations
        .allSources
        .flatMap { source =>
          relations.libraryDeps(source)
        }
        .toSet
    external ++ library
  }
}
