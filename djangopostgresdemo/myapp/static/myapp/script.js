// Initializes DataTables and debounces radio filter changes.
// Requires jQuery + DataTables to be loaded before this file.
jQuery(function ($) {
    // Init DataTable on the submissions table
    var $table = $('#submissionstable');
    if ($table.length && !$.fn.dataTable.isDataTable($table)) {
        $table.DataTable({
            responsive: true,
            scrollY: '300px',
            scrollCollapse: true,
            paging: true,
            pageLength: 50,
            lengthMenu: [[25, 50, 100, -1], [25, 50, 100, 'All']],
            order: [[0, 'desc']]
        });
    }

    // Debounce radio filter changes to avoid rapid full-page reloads
    var debounceTimer = null;
    var DEBOUNCE_MS = 300;
    $(document).on('change', 'input[name="filter_by"]', function (e) {
        if (debounceTimer) clearTimeout(debounceTimer);
        // prevent any inline handlers from immediately submitting the form
        e.stopImmediatePropagation();
        debounceTimer = setTimeout(function () {
            var val = $('input[name="filter_by"]:checked').val();
            var params = new URLSearchParams(window.location.search);
            params.set('filter_by', val);
            params.delete('page'); // reset page when filtering
            window.location.search = params.toString();
        }, DEBOUNCE_MS);
    });
});