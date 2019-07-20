package org.pantsbuild.scoverage.report

import java.io.File
import org.pantsbuild.zinc.options.Parsed
import org.apache.commons.io.FileUtils
import sbt.internal.util.ConsoleLogger
import scoverage.{Coverage, IOUtils, Serializer}
import scoverage.report.{ScoverageHtmlWriter, ScoverageXmlWriter}

object ScoverageRep {
  val Scoverage = "scoverage"

  // Copying the logger from org.pantsbuild.zinc.bootstrap
  // As per https://github.com/pantsbuild/pants/issues/6160, this is a workaround
  // so we can run zinc without $PATH (as needed in remoting).
  System.setProperty("sbt.log.format", "true")

  val cl = ConsoleLogger.apply()

  case class ReportOptions(
    loadDataDir: Boolean,
    measurementsPath: String,
    sourcePath: String,
    reportPath: String,
    dataPath: String,
    writeHtml: Boolean,
    writeXml: Boolean,
    writeXmlDebug: Boolean,
    cleanOld: Boolean,
    targetFilters: Seq[String]
  ) {
    val writeReports: Boolean = {
      val write = writeHtml || writeXml
      if (!write) {
        // we could end here, but we will still attempt to load the coverage and dump stats as info
        // to the log, so maybe somebody would want to run this w/o generating reports?
        cl.warn("No report output format specified, so no reports will be written.")
      }
      write
    }
  }

  object ReportOptions {
    def apply(settings: Settings): ReportOptions = {
      ReportOptions(
        loadDataDir = settings.loadDataDir,
        measurementsPath = settings.measurementsDirPath,
        sourcePath = settings.sourceDirPath,
        reportPath = settings.reportDirPath,
        dataPath = settings.dataDirPath,
        writeHtml = settings.writeHtmlReport,
        writeXml = settings.writeXmlReport,
        writeXmlDebug = settings.writeXmlDebug,
        cleanOld = settings.cleanOldReports,
        targetFilters = settings.targetFilters
      )
    }
  }

  /**
   *
   * @param dataDirs list of measurement directories for which coverage
   *                 report has to be generated
   * @return         [Coverage] object for the [dataDirs]
   */
  private def aggregatedCoverage(dataDirs: Seq[File]): Coverage = {
    var id = 0
    val coverage = Coverage()
    dataDirs foreach { dataDir =>
      val coverageFile: File = Serializer.coverageFile(dataDir)
      if (coverageFile.exists) {
        val subcoverage: Coverage = Serializer.deserialize(coverageFile)
        val measurementFiles: Array[File] = IOUtils.findMeasurementFiles(dataDir)
        val measurements = IOUtils.invoked(measurementFiles.toIndexedSeq)
        subcoverage.apply(measurements)
        subcoverage.statements foreach { stmt =>
          // need to ensure all the ids are unique otherwise the coverage object will have stmt collisions
          id = id + 1
          coverage add stmt.copy(id = id)
        }
      }
    }
    coverage
  }

  /**
   *
   * @param dataDirs list of measurement directories for which coverage
   *                 report has to be generated
   * @return         Coverage object wrapped in Option
   */
  private def aggregate(dataDirs: Seq[File]): Option[Coverage] = {
    cl.success(s"Found ${dataDirs.size} subproject scoverage data directories [${dataDirs.mkString(",")}]")
    if (dataDirs.nonEmpty) {
      Some(aggregatedCoverage(dataDirs))
    } else {
      None
    }
  }

  /**
   * Select the appropriate directories for which the scoverage report has
   * to be generated. If [targetFiles] is empty, report is generated for all
   * measurements directories inside in [dataDir].
   */
  private def filterFiles(dataDir: File, options: ReportOptions): Seq[File] = {
    val targetFiles = options.targetFilters

    if(targetFiles.nonEmpty) {
      cl.info(s"Looking for targets: $targetFiles")
      dataDir.listFiles.filter(_.isDirectory).toSeq.filter {
        file => targetFiles.contains(file.getName())
      }
    }
    else {
      dataDir.listFiles.filter(_.isDirectory).toSeq
    }
  }

  /**
   * Aggregating coverage from all the coverage measurements.
   */
  private def loadAggregatedCoverage(dataPath: String, options: ReportOptions): Option[Coverage] = {
    val dataDir: File = new File(dataPath)
    cl.info(s"Attempting to open scoverage data dir: [$dataDir]")
    if(dataDir.exists){
      cl.info(s"Aggregating coverage.")
      val dataDirs: Seq[File] = filterFiles(dataDir, options)
      aggregate(dataDirs)
    }
    else {
      cl.error("Coverage directory does not exists.")
      None
    }
  }

  /**
   * Loads coverage data from the specified data directory.
   */
  private def loadCoverage(dataPath: String): Option[Coverage] = {
    val dataDir: File = new File(dataPath)
    cl.info(s"Attempting to open scoverage data dir [$dataDir]")

    if (dataDir.exists) {
      val coverageFile = Serializer.coverageFile(dataDir)
      cl.info(s"Reading scoverage instrumentation [$coverageFile]")

      coverageFile.exists match {
        case true =>
          val coverage = Serializer.deserialize(coverageFile)
          cl.info(s"Reading scoverage measurements...")

          val measurementFiles = IOUtils.findMeasurementFiles(dataDir)
          val measurements = IOUtils.invoked(measurementFiles)
          coverage.apply(measurements)
          Some(coverage)

        case false =>
          cl.error("Coverage file did not exist")
          None

      }
    } else {
      cl.error("Data dir did not exist!")
      None
    }

  }

  /**
   * Writes coverage reports usign the specified source path to the specified report directory.
   */
  private def writeReports(coverage: Coverage, options: ReportOptions): Unit = {
    val sourceDir = new File(options.sourcePath)
    val reportDir = new File(options.reportPath)
    val reportDirHtml = new File(options.reportPath + "/html")
    val reportDirXml = new File(options.reportPath + "/xml")

    if (sourceDir.exists) {
      if (options.cleanOld && reportDir.exists) {
        cl.info(s"Nuking old report directory [$reportDir].")
        FileUtils.deleteDirectory(reportDir)
      }

      if (!reportDir.exists) {
        cl.info(s"Creating HTML report directory [$reportDirHtml]")
        reportDirHtml.mkdirs
        cl.info(s"Creating XML report directory [$reportDirXml]")
        reportDirXml.mkdirs
      }

      if (options.writeHtml) {
        cl.info(s"Writing HTML scoverage reports to [$reportDirHtml]")
        new ScoverageHtmlWriter(Seq(sourceDir), reportDirHtml, None).write(coverage)
      }

      if (options.writeXml) {
        cl.info(s"Writing XML scoverage reports to [$reportDirXml]")
        new ScoverageXmlWriter(Seq(sourceDir), reportDirXml, false).write(coverage)
        if (options.writeXmlDebug) {
          new ScoverageXmlWriter(Seq(sourceDir), reportDirXml, true).write(coverage)
        }
      }
    } else {
      cl.error(s"Source dir [$sourceDir] does not exist")
    }

    cl.success(s"Statement coverage: ${coverage.statementCoverageFormatted}%")
    cl.success(s"Branch coverage:    ${coverage.branchCoverageFormatted}%")
  }


  def main(args: Array[String]): Unit = {
    val Parsed(settings, residual, errors) = Settings.parse(args)
    val reportOptions = ReportOptions(settings)

    // bail out on any command-line option errors
    if (errors.nonEmpty) {
      for (error <- errors) System.err.println(error)
      System.err.println("See %s -help for information about options" format Scoverage)
      sys.exit(1)
    }

    if (settings.help) {
      Settings.printUsage(Scoverage)
      return
    }

    settings.loadDataDir match {
      case false =>
        loadAggregatedCoverage(reportOptions.measurementsPath, reportOptions) match {
          case Some(cov) =>
            cl.success("Coverage loaded successfully.\n")
            if (reportOptions.writeReports) {
              writeReports(cov, reportOptions)
            }

          case None => cl.error("Failed to load coverage.")
        }
      case true =>
        loadCoverage(reportOptions.dataPath) match {
          case Some(cov) =>
            cl.success("Coverage loaded successfully!")
            if (reportOptions.writeReports) {
              writeReports(cov, reportOptions)
            }
          case _ => cl.error("Failed to load coverage")
        }
    }

  }
}
