/**
 * Copyright (C) 2017 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

package org.pantsbuild.zinc.extractor

import java.io.File

import scala.collection.mutable

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
   */
  def dependencies: collection.Map[File, collection.Set[File]] = {
    val mm = new mutable.HashMap[File, mutable.Set[File]] with mutable.MultiMap[File, File]

    // Look up the external deps for each classfile for each sourcefile.
    for {
      source <- relations.allSources
      _ = println(s">>> source: $source")
      sourceClassname <- relations.classNames(source)
      _ = println(s">>>   sourceClassname: $sourceClassname")
      classname <- relations.externalDeps(sourceClassname)
      _ = println(s">>>     classname: $classname")
      dep <- warningDefinesClass(classname)
      _ = println(s">>>       dep: $dep")
    } {
      mm.addBinding(source, dep)
    }

    // And library dependencies.
    for {
      source <- relations.allSources
      _ = println(s">>> source: $source")
      dep <- relations.libraryDeps(source)
      _ = println(s">>>   dep: $dep")
    } {
      mm.addBinding(source, dep)
    }

    mm
  }

  private def warningDefinesClass(classname: String): Option[File] =
    definesClass(classname).orElse {
      // This case should be rare: should only occur when a compiler plugin generates
      // additional classes.
      System.err.println(s"No analysis declares class $classname")
      None
    }
}
