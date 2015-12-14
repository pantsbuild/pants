// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

// Namespacing.
pants = pants || {};
pants.stats = pants.stats || {};
pants.stats.chart = pants.stats.chart || {};


// A line chart showing stats over a date range.  Can overlay charts for a workunit and
// any of its immediate sub-workunits.
pants.stats.chart.init = function(selector, matrix) {
  // Workunits for which we're currently showing charts.
  var chartedWorkunits = [];

  var dataView = createDataView();

  function colIdx(workunit) {
    return 1 + matrix.getColIdx(workunit);
  }

  // Create the DataView for a line chart.
  function createDataView() {
    var table = new google.visualization.DataTable();
    table.addColumn('string', 'Date');
    matrix.eachColumnLabel(function (workunit) {
      table.addColumn('number', workunit)
    });
    matrix.eachRow(function(dt, rowData) {
      table.addRow([dt].concat(rowData));
    });
    return new google.visualization.DataView(table);
  }

  function resetCharts(workunit) {
    // Initially we show only the chart for the workunit, not for any of its descendants.
    chartedWorkunits = [workunit];
    dataView.setColumns([0, colIdx(workunit)]);
    redraw();
  }

  function showChart(workunit) {
    chartedWorkunits = _.union(chartedWorkunits, [workunit]);
    // Note that col 0 is the date, so data cols are offset by 1.
    var chartIdxs = _.map(chartedWorkunits, colIdx);
    dataView.setColumns([0].concat(chartIdxs));
    redraw();
  }

  function hideChart(workunit) {
    chartedWorkunits = _.difference(chartedWorkunits, [workunit]);
    dataView.hideColumns([colIdx(workunit)]);
    redraw();
  }

  function redraw() {
    // TODO: When the Material Design options schema is out of beta, use it here and
    // remove the call to convertOptions below.
    var options = {
      titlePosition: 'none',
      chartArea: {top: 20, height: '80%'},
      height: 300,
      vAxis: {
        title: 'Time (ms)',
        minValue: 0
      },
      pointSize: 3,
      annotations: {
        style: 'line'
      }
    };
    var lineChart = new google.charts.Line($(selector).get(0));
    lineChart.draw(dataView, google.charts.Line.convertOptions(options));

    google.visualization.events.addListener(lineChart, 'select', function() {
      var selectedItem = lineChart.getSelection()[0];
      if (selectedItem) {
        var date = dataView.getFormattedValue(selectedItem.row, 0);
        $(document).triggerHandler('pants:date:select', {date: date});
      }
    });
  }

  // Set up event handling.

  $(document).on('pants:stats:show', function(e, data) {
    resetCharts(data.workunit);
  });

  $(document).on('pants:chart:show', function(e, data) {
    showChart(data.workunit);
  });

  $(document).on('pants:chart:hide', function(e, data) {
    hideChart(data.workunit);
  });
};
