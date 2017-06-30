/**
 * Copyright (C) 2017 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

package org.pantsbuild.zinc.extractor

import java.io.File

import sbt.internal.inc.{Analysis, FileBasedStore}

import xsbti.compile.CompileAnalysis


/**
 * Class to encapsulate extracting analysis
 */
class Extractor(_analysis: CompileAnalysis) {
  private val relations = _analysis.asInstanceOf[Analysis].relations

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
        .flatMap(relations.libraryDefinesClass)
        .toSet

    println(external)

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
