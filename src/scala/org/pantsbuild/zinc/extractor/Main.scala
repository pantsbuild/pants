/**
 * Copyright (C) 2017 Pants project contributors (see CONTRIBUTORS.md).
 * Licensed under the Apache License, Version 2.0 (see LICENSE).
 */

package org.pantsbuild.zinc.extractor

import java.io.File

import scala.compat.java8.OptionConverters._

import sbt.internal.inc.text.TextAnalysisFormat

import com.fasterxml.jackson.databind.ObjectMapper
import com.fasterxml.jackson.module.scala.DefaultScalaModule
import com.fasterxml.jackson.module.scala.experimental.ScalaObjectMapper

import com.google.common.base.Charsets
import com.google.common.io.Files

import org.pantsbuild.zinc.analysis.{AnalysisMap, PortableAnalysisMappers}
import org.pantsbuild.zinc.options.Parsed

/**
 * Command-line main class for analysis extraction.
 */
object Main {
  val Command = "zinc-extractor"

  private val om = {
    val mapper = new ObjectMapper with ScalaObjectMapper
    mapper.registerModule(DefaultScalaModule)
    mapper
  }

  /**
   * Write a summary of products and dependencies.
   */
  def summarize(summaryJson: File, extractor: Extractor) {
    om.writeValue(
      summaryJson,
      Summary(
        extractor.products,
        extractor.dependencies
      )
    )
  }

  /**
   * Dump a human readable debug form of the analysis to the given file.
   */
  def dump(debugDump: File, extractor: Extractor) {
    val writer = Files.asCharSink(debugDump, Charsets.UTF_8).openBufferedStream()
    try {
      TextAnalysisFormat.write(writer, extractor.analysis.getAnalysis, extractor.analysis.getMiniSetup)
    } finally {
      writer.close()
    }
  }

  def main(args: Array[String]): Unit = {
    val Parsed(settings, residual, errors) = Settings.parse(args)

    // bail out on any command-line option errors
    if (errors.nonEmpty) {
      for (error <- errors) System.err.println(error)
      System.err.println("See %s -help for information about options" format Command)
      sys.exit(1)
    }

    if (settings.help) {
      Settings.printUsage(Command)
      return
    }

    // Load relevant analysis.
    val analysisMap = AnalysisMap.create(settings.analysis)
    val analysis =
      analysisMap.cachedStore(settings.analysis.cache)
        .get()
        .asScala
        .getOrElse {
          throw new RuntimeException(s"Failed to load analysis from ${settings.analysis.cache}")
        }

    val extractor = new Extractor(settings.classpath, analysis, analysisMap)

    (settings.summaryJson, settings.debugDump) match {
      case (Some(summaryJson), None) =>
        summarize(summaryJson, extractor)
      case (None, Some(debugDump)) =>
        dump(debugDump, extractor)
      case (summaryJson, debugDump) =>
        throw new RuntimeException(
          s"Exactly one output mode was expected: got $summaryJson and $debugDump.")
    }
  }
}

case class Summary(
  products: collection.Map[File, collection.Set[File]],
  dependencies: collection.Map[File, collection.Set[File]]
)
