#!/bin/bash
set -e

RESULTS_DIR="$(pwd)/test-results"
mkdir -p "$RESULTS_DIR"

#pytest tools/azdisc/tests/ --junitxml="$RESULTS_DIR/results.xml" --tb=short
# Resource catalog regression gates are enforced by
# TestResourceCatalogThresholds in tools/azdisc/tests/test_integration.py.
# Update tools/azdisc/tests/fixtures/resource_catalog_thresholds.json
# intentionally when a planned baseline shift occurs.
pytest tools/azdisc/tests/ --html="$RESULTS_DIR/report.html"
#echo "Test results saved to $RESULTS_DIR/results.xml"
echo "HTML report saved to $RESULTS_DIR/report.html"
