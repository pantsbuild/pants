// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

// Namespacing.
pants = pants || {};
pants.stats = pants.stats || {};
pants.stats.table = pants.stats.table || {};


// A table showing the stats breakdown under a given workunit, on a certain date.
pants.stats.table.init = function(selector, matrix) {
  // The workunit we're currently showing table entries for.
  var currentWorkunit = 'main';

  // CSS classes for anchor tags used to drill down into workunits, and for checkboxes
  // used to show/hide graphs for workunits. We use these to set up click handlers on
  // the elements after the visualization layer draws them.
  var anchorClass = 'stats-workunit-anchor';
  var checkboxClass = 'stats-workunit-checkbox';

  var workunitClassPrefix = 'acts-on-workunit-';

  // A workunit-specific class name, so that DOM event handlers can know which workunit they were
  // invoked for. Note that we replace ':' with '_' in workunit names, so they're css-name safe.
  // We don't use a dash because we allow those in workunit names.
  function workunitClass(workunit) {
    return workunitClassPrefix + workunit.replace(/:/g, '_');
  }

  var dataView;

  function createDataView(forDate) {
    // Note that table rows correspond to matrix columns.
    var table = new google.visualization.DataTable();
    table.addColumn('string', 'Chart');
    table.addColumn('string', 'Work Unit');
    table.addColumn('number', 'Time');
    table.addColumn('number', '%');

    var dailyTotal = matrix.get(forDate, 'main');

    matrix.eachColumnLabel(function(workunit) {
      var dailyTimingForLabel = matrix.get(forDate, workunit);
      table.addRow([
        '<input type="checkbox" ' +
        'class="' + checkboxClass + ' ' + workunitClass(workunit) + '"/>',
        '<a href="#" class="' + anchorClass + ' ' + workunitClass(workunit) + '">' +
          workunit + '</a>',
        dailyTimingForLabel,
        dailyTotal ? 100 * dailyTimingForLabel / dailyTotal : 0
      ]);
    });

    new google.visualization.NumberFormat({
      fractionDigits: 0,
      suffix: ' ms'
    }).format(table, 2);
    new google.visualization.NumberFormat({
      fractionDigits: 2,
      suffix: '%'
    }).format(table, 3);

    dataView = new google.visualization.DataView(table);
  }

  function redraw() {
    var table = new google.visualization.Table($(selector).get(0));
    table.draw(dataView, {
      showRowNumber: true,
      sortColumn: 2,
      sortAscending: false,
      allowHtml: true
    });


    // Set up click handlers. Note that we must do this here after the table is drawn by the
    // visualization library, so that the DOM elements we attach the handlers to actually exist.

    function triggerOnWorkunit(evt, handler) {
      evt.preventDefault();
      var match = evt.target.className.match(new RegExp(workunitClassPrefix + '(\\S+)'));
      if (match) {
        var workunit = match[1].replace(/_/g, ':');
        $(document).triggerHandler(handler, { workunit: workunit });
      }
      return false;
    }

    $('.' + anchorClass).click(function(evt) {
      return triggerOnWorkunit(evt, 'pants:stats:show');
    });

    $('.' + checkboxClass).change(function(evt) {
      var handler = 'pants:chart:' + (($(this).is(':checked')) ? 'show' : 'hide');
      return triggerOnWorkunit(evt, handler);
    });
  }

  function showForWorkunit(workunit) {
    // Show table rows for the workunit and its immediate descendants.
    currentWorkunit = workunit;
    var workunitsToShow = matrix.filterColumnLabel(function(wu) {
      return s.startsWith(wu, workunit) &&
          s.count(wu.substring(workunit.length), ':') <= 1;
    });
    var workunitIdxs = _.map(workunitsToShow, function (wu) {
      return matrix.getColIdx(wu);
    });
    dataView.setRows(workunitIdxs);

    redraw();

    // Check the box for the workunit (but not its descendants).
    $('.' + checkboxClass + '.' + workunitClass(workunit)).prop('checked', true);
  }

  // Set up event handling.

  $(document).on('pants:stats:show', function(e, data) {
    showForWorkunit(data.workunit);
  });

  $(document).on('pants:date:select', function(e, data) {
    createDataView(data.date);
    showForWorkunit(currentWorkunit);
  });
};
