package org.pantsbuild.backend.kotlin.dependency_inference

import java.io.File
import java.io.FileWriter

fun main(args: Array<String>) {
    val analysisOutputPath = args[0]
    val sourceToAnalyze = args[1]

    val outputFile = File(analysisOutputPath)
    val writer = FileWriter(outputFile)
    writer.write("{\"imports\":[]}")
    writer.close()
}
