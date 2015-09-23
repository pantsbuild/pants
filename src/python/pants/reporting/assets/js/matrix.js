// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).


// Namespacing.
pants = pants || {};
pants.matrix = pants.matrix || {};


// A plain old m x n, integer-index matrix.
pants.matrix.createMatrix = function(m, n) {
  var rows = [];  // We store in row-first order.
  for (var i = 0; i < m; i++) {  // Initialize to all zeros.
    rows.push(_.times(n, _.constant(0)));
  }

  return {
    get: function(i, j) { return rows[i][j]; },
    set: function(i, j, val) { rows[i][j] = val; },
    getRow: function(i) { return rows[i]; }
  };
};


// A matrix in which the (row, col) is specified by text labels instead of indexes.
pants.matrix.createLabeledMatrix = function(rowLabels, colLabels) {
  var matrix = pants.matrix.createMatrix(rowLabels.length, colLabels.length);
  var rowLabelToIdx = _.object(rowLabels, _.range(rowLabels.length));
  var colLabelToIdx = _.object(colLabels, _.range(colLabels.length));

  function getRowIdx(rowLabel) {
    var ret = rowLabelToIdx[rowLabel];
    if (ret === undefined) { console.log('Unknown row label: ' + rowLabel); }
    return ret
  }

  function getColIdx(colLabel) {
    var ret = colLabelToIdx[colLabel];
    if (ret === undefined) { console.log('Unknown col label: ' + colLabel); }
    return ret
  }

  return {
    get: function(rowLabel, colLabel) {
      return matrix.get(getRowIdx(rowLabel), getColIdx(colLabel));
    },
    set: function(rowLabel, colLabel, val) {
      matrix.set(getRowIdx(rowLabel), getColIdx(colLabel), val);
    },
    getRow: function(rowLabel) {
      return matrix.getRow(getRowIdx(rowLabel));
    },
    eachRow: function(callback) {  // callback: function(rowLabel, rowData).
      _.each(rowLabels, function(label) { callback(label, matrix.getRow(getRowIdx(label))); });
    },
    getColIdx: function(colLabel) {
      return getColIdx(colLabel);
    },
    eachColumnLabel: function(callback) {  // callback: function(colLabel);
      _.each(colLabels, callback);
    },
    filterColumnLabel: function(filter) {  // filter: function(colLabel) => bool;
      return _.filter(colLabels, filter);
    }
  }
};


// A matrix of statsData in which the rows are labeled by dates and the columns by workunits.
// The argument is jsonified stats data as returned by StatsDB.get_aggregated_stats_for_cmd_line().
pants.matrix.createDateWorkunitMatrix = function(statsData) {
  function dateToString(dt) {
    function twoDigit(x) { return (x < 10) ? '0' + x : '' + x; }
    return dt.getUTCFullYear() + '-' +
        twoDigit(dt.getUTCMonth() + 1) + '-' +
        twoDigit(dt.getUTCDate());
  }

  // Find all known date labels.
  var minDate = '9999-99-99';
  var maxDate = '';
  _.each(statsData, function(stat) {
    var dt = stat[0];
    minDate = (dt < minDate) ? dt : minDate;
    maxDate = (dt > maxDate) ? dt : maxDate;
  });
  var minDateObj = new Date(minDate);
  var maxDateObj = new Date(maxDate);

  var dateLabels = [];
  for (var dt = minDateObj; dt <= maxDateObj; dt.setDate(dt.getDate() + 1)) {
    dateLabels.push(dateToString(dt));
  }

  var workunitLabels = _.uniq(_.map(statsData, function (stat) { return stat[1]; }).sort(), true);

  var matrix = pants.matrix.createLabeledMatrix(dateLabels, workunitLabels);
  _.each(statsData, function (stat) {
    var dt = stat[0];
    var workunit = stat[1];
    var timing = stat[3];
    matrix.set(dt, workunit, timing);
  });
  return matrix;
};
