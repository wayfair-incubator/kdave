#!/usr/bin/env bash

set -e

ACTIVATE_PYENV="true"
BLACK_ACTION="--check"
ISORT_ACTION="--check-only"
TEST_DIRS="./tests"
COV_REPORT="--cov-report html"

function usage
{
    echo "usage: run_tests.sh [--format-code] [--no-pyenv]"
    echo ""
    echo " --ci          : Do extra work to support CI pipeline."
    echo " --format-code : Format the code instead of checking formatting."
    echo " --no-pyenv    : Don't activate the pyenv virtualenv"
    exit 1
}

while [[ $# -gt 0 ]]; do
    arg="$1"
    case $arg in
        --format-code)
        BLACK_ACTION="--quiet"
        ISORT_ACTION="--apply"
        ;;
        --no-pyenv)
        ACTIVATE_PYENV="false"
        ;;
        --ci)
        COV_REPORT=""
        ;;
        -h|--help)
        usage
        ;;
        *)
        echo "Unexpected argument: ${arg}"
        usage
        ;;
        "")
        # ignore
        ;;
    esac
    shift
done

# only generate html locally
pytest -x -vv ${TEST_DIRS} ${COV_REPORT}

echo "Running MyPy..."
mypy exporter

echo "Running black..."
black ${BLACK_ACTION} exporter tests

echo "Running flake8..."
flake8 exporter tests

echo "Running bandit..."
bandit --ini .bandit -r exporter

echo "Running iSort..."
isort --recursive ${ISORT_ACTION} exporter tests