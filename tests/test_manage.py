from exporter import manage
from exporter.constants import DEPRECATED_API_EXIT_CODE, HELM_V2_BINARY
from exporter.exceptions import (
    DeprecatedAPIVersionError,
    RemovedAPIVersionError,
    RemovedNextReleaseAPIVersionError,
)


def test_cli__check__call_args(mocker, cli_runner):
    check_deprecations_all_mocker = mocker.patch(
        "exporter.manage.check_deprecations_all"
    )

    cli_runner.invoke(
        manage.check,
        [
            "--source",
            "tests/fixtures/single-document.yaml",
            "--tabulate",
            "--version",
            "1.10.0",
            "--output-dir",
            "/tmp/helm",
        ],
    )

    check_deprecations_all_mocker.assert_called_once_with(
        "tests/fixtures/single-document.yaml",
        HELM_V2_BINARY,
        tabulate=True,
        k8s_version="1.10.0",
        chart=None,
        format=False,
        message=False,
        namespace=None,
        release=None,
        values=None,
        custom_values=None,
        skip_dependencies=False,
        output_dir="/tmp/helm",
    )


def test_cli__deprecated_api_versions__return_zero_exit_code(mocker, cli_runner):
    mocker.patch(
        "exporter.manage.check_deprecations_all", side_effect=DeprecatedAPIVersionError
    )

    result = cli_runner.invoke(
        manage.check,
        [
            "--source",
            "tests/fixtures/single-document.yaml",
            "--tabulate",
            "--version",
            "1.10.0",
            "--output-dir",
            "/tmp/helm",
        ],
    )

    assert result.exit_code == DEPRECATED_API_EXIT_CODE


def test_cli__removed_api_versions__change_exit_code__success(mocker, cli_runner):
    mocker.patch(
        "exporter.manage.check_deprecations_all", side_effect=RemovedAPIVersionError
    )

    result = cli_runner.invoke(
        manage.check,
        [
            "--source",
            "tests/fixtures/single-document.yaml",
            "--tabulate",
            "--version",
            "1.10.0",
            "--output-dir",
            "/tmp/helm",
            "--removed-apis-exit-code",
            70,
        ],
    )

    assert result.exit_code == 70


def test_cli__removed_next_release_api_versions__overwrite_deprecated_exit_code__success(
    mocker, cli_runner
):
    mocker.patch(
        "exporter.manage.check_deprecations_all",
        side_effect=RemovedNextReleaseAPIVersionError,
    )

    result = cli_runner.invoke(
        manage.check,
        [
            "--source",
            "tests/fixtures/single-document.yaml",
            "--tabulate",
            "--version",
            "1.10.0",
            "--output-dir",
            "/tmp/helm",
            "--deprecated-apis-exit-code",
            10,
            "--removed-apis-in-next-release-exit-code",
            80,
        ],
    )

    assert result.exit_code == 80
