package org.pantsbuild.scoverage.report

/**
 * All parsed command-line options.
 */
case class Settings(
  loadDataDir: Boolean = false,
  measurementsDirPath: String = "",
  sourceDirPath: String = ".",
  dataDirPath: String = "",
  htmlDirPath: String = "",
  xmlDirPath: String = "",
  xmlDebugDirPath: String = "",
  cleanOldReports: Boolean = false,
  targetFilters: Seq[String] = Seq(),
  outputAsCobertura: Boolean = false)

object Settings {

  val parser1 = new scopt.OptionParser[Settings]("scoverage") {
    head("scoverageReportGenerator")

    help("help")
      .text("Print this usage message.")

    opt[Unit]("loadDataDir")
      .action((_, s: Settings) => s.copy(loadDataDir = true))
      .text("Load a single measurements directory instead of aggregating coverage reports. Must pass in `dataDirPath <dir>`")

    opt[String]("measurementsDirPath")
      .action((dir: String, s: Settings) => s.copy(measurementsDirPath = dir))
      .text("Directory where all scoverage measurements data is stored.")

    opt[String]("sourceDirPath")
      .action((dir: String, s: Settings) => s.copy(sourceDirPath = dir))
      .text("Directory containing the project sources.")

    opt[String]("dataDirPath")
      .action((dir: String, s: Settings) => s.copy(dataDirPath = dir))
      .text("Scoverage data file directory to be used in case report needed for single measurements " +
        "directory. Must set `loadDataDir` to use this options.")

    opt[String]("htmlDirPath")
      .action((dir: String, s: Settings) => s.copy(htmlDirPath = dir))
      .text("Target output directory to place the html reports.")

    opt[String]("xmlDirPath")
      .action((dir: String, s: Settings) => s.copy(xmlDirPath = dir))
      .text("Target output directory to place the xml reports.")

    opt[String]("xmlDebugDirPath")
      .action((dir: String, s: Settings) => s.copy(xmlDebugDirPath = dir))
      .text("Target output directory to place the xml debug reports.")

    opt[Unit]("cleanOldReports")
      .action((_, s: Settings) => s.copy(cleanOldReports = true))
      .text("Delete any existing reports directory prior to writing reports.")

    opt[Seq[String]]("targetFilters")
      .action((f: Seq[String], s: Settings) => s.copy(targetFilters = f))
      .text("Directory names for which report has to be generated.")

    opt[Unit]("outputAsCobertura")
      .action((_, s: Settings) => s.copy(outputAsCobertura = true))
      .text("Export Cobertura formats for Scoverage.")
  }
}
