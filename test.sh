#!/bin/bash
set -e

RESULTS_DIR="$(pwd)/test-results"
mkdir -p "$RESULTS_DIR"

#pytest tools/azdisc/tests/ --junitxml="$RESULTS_DIR/results.xml" --tb=short
pytest tools/azdisc/tests/ --html="$RESULTS_DIR/report.html"
#echo "Test results saved to $RESULTS_DIR/results.xml"
echo "HTML report saved to $RESULTS_DIR/report.html"
