# import logging

import io
import json
import subprocess  # nosec
from contextlib import redirect_stdout
from unittest.mock import MagicMock

import pytest

from exporter import helper
from exporter.constants import HELM_TEMPLATE_TMP_DIRECTORY, HELM_V2_BINARY
from exporter.exceptions import (
    HelmChartYamlFileMissing,
    HelmCommandError,
    K8sYAMLReadError,
)


def test_load_yaml_file__non_existing_file__raises_k8s_yaml_read_error(tmpdir):
    # Without writing something in the file, it won't be created.
    file = tmpdir.join("tmp.yaml")
    with pytest.raises(K8sYAMLReadError):
        helper.load_yaml_file(file)


def test_load_yaml_file__success():
    data = helper.load_yaml_file("tests/fixtures/file.yaml")
    assert data is not None
    assert isinstance(data, dict)
    assert data["kind"] == "PodSecurityPolicy"


def test_load_multiple_yaml_documents__success():
    data = helper.load_multiple_yaml_documents(
        "tests/fixtures/multi-document-file.yaml"
    )
    assert isinstance(data, list)
    assert data is not None
    assert isinstance(data[0], dict)
    assert data[0] is not None


def test_load_multiple_yaml_documents__empty_file__raises_k8s_yaml_read_error(tmpdir):
    file = tmpdir.join("tmp.yaml")
    with pytest.raises(K8sYAMLReadError):
        helper.load_multiple_yaml_documents(file)


def test_file_handler_load__success(tmpdir):
    _file = tmpdir.join("tmp.yaml")
    data = {"foo": "bar"}

    _file.write(json.dumps(data))
    file = helper.FileHandler(_file)
    f = file.load()
    assert f["foo"] == "bar"


def test_file_handler_save__success(tmpdir):
    _file = tmpdir.join("tmp.yaml")
    data = {"foo": "bar"}

    file = helper.FileHandler(_file)
    file.save(json.dumps(data))
    f = file.load()
    assert f["foo"] == "bar"


def test_applogger__success(caplog):
    logger = helper.applogger("exporter")
    logger.propagate = True

    logger.debug("message")
    assert "message" in caplog.text


def test_table_decorator__success():
    @helper._table
    def print_table():
        msg = ""
        table_data = []
        title = ["Key-1", "Key-2", "Key-3"]
        data = ["Value-1", "value-2", "value-3"]

        table_data.append([word for word in title])
        table_data.append(data)

        return table_data, msg

    f = io.StringIO()
    with redirect_stdout(f):
        print_table()
    actual = f.getvalue()

    assert actual == (
        "+---------+---------+---------+\n"
        "| Key-1   | Key-2   | Key-3   |\n"
        "+---------+---------+---------+\n"
        "| Value-1 | value-2 | value-3 |\n"
        "+---------+---------+---------+\n"
    )


def test_get_chart_name__missing_chart_yaml_file__raises_missing_chart_yaml_error():
    chart_with_missing_chart_dot_yaml = "tests/fixtures/chart-missing-yaml"

    with pytest.raises(HelmChartYamlFileMissing):
        helper.get_chart_name(chart_with_missing_chart_dot_yaml)


def test_get_chart_name__success():
    chart_with_chart_dot_yaml = "tests/fixtures/nginx"

    name = helper.get_chart_name(chart_with_chart_dot_yaml)
    assert name == "ingress-nginx"


def test_helm_template__success(mocker):
    sub_process_mock = mocker.patch("subprocess.run")

    chart_path = "tests/fixtures/nginx"
    output_dir = "/tmp/tmp_helm"

    helper.helm_template(chart_path, output_dir, HELM_V2_BINARY)

    helm_command = [
        "helm",
        "template",
        chart_path,
        "--name",
        "ingress-nginx",
        "--output-dir",
        output_dir,
    ]

    sub_process_mock.assert_called_with(
        helm_command, capture_output=True, check=True, stdout=None
    )


def test_helm_template__passing_custom_values_file__success(mocker):
    sub_process_mock = mocker.patch("subprocess.run")

    chart_path = "tests/fixtures/nginx"
    output_dir = HELM_TEMPLATE_TMP_DIRECTORY
    values = "/tmp/values.yaml"

    helper.helm_template(chart_path, output_dir, HELM_V2_BINARY, values)

    helm_command = [
        "helm",
        "template",
        chart_path,
        "--name",
        "ingress-nginx",
        "--values",
        values,
        "--output-dir",
        output_dir,
    ]

    sub_process_mock.assert_called_with(
        helm_command, capture_output=True, check=True, stdout=None
    )


def test_helm_template__subproces_error__raises_helm_command_error(mocker):
    mocker.patch(
        "subprocess.run",
        side_effect=subprocess.CalledProcessError(
            1,
            [
                HELM_V2_BINARY,
                "template",
                "chart_path",
                "--name",
                "name",
                "--output-dir",
                HELM_TEMPLATE_TMP_DIRECTORY,
            ],
        ),
    )
    with pytest.raises(HelmCommandError):
        helper.helm_template(
            "tests/fixtures/nginx", HELM_TEMPLATE_TMP_DIRECTORY, HELM_V2_BINARY
        )


def test_helm_build_dependencies__success(mocker):
    sub_process_mock = mocker.patch("subprocess.run")

    chart_path = "tests/fixtures/chart-with-dependencies"

    helper.helm_build_dependencies(HELM_V2_BINARY, chart_path)

    helm_command = [HELM_V2_BINARY, "dependency", "update", chart_path]

    sub_process_mock.assert_called_with(
        helm_command, capture_output=True, check=True, stdout=None
    )


def test_helm_list_namespace_releases__success(mocker):
    mock_stdout = MagicMock()
    mock_stdout.configure_mock(**{"stdout.decode.return_value": "{}"})

    sub_process_mock = mocker.patch(
        "exporter.helper.subprocess.run", return_value=mock_stdout
    )
    namespace = "default"

    helper.helm_list_namespace_releases(HELM_V2_BINARY, namespace)
    helm_command = [
        HELM_V2_BINARY,
        "list",
        "--namespace",
        f"{namespace}",
        "--output",
        "yaml",
    ]

    sub_process_mock.assert_called_with(
        helm_command, capture_output=True, check=True, stdout=None
    )


def test_helm_list_namespace_releases__return_releases__success(mocker):
    mock_stdout = MagicMock()
    result = {
        "Releases": [
            {"Name": "release-1"},
            {"Name": "release-2"},
            {"Name": "release-3"},
        ]
    }
    mock_stdout.configure_mock(**{"stdout.decode.return_value": str(result)})

    mocker.patch("exporter.helper.subprocess.run", return_value=mock_stdout)
    namespace = "default"

    assert helper.helm_list_namespace_releases(HELM_V2_BINARY, namespace) == [
        "release-1",
        "release-2",
        "release-3",
    ]


def test_helm_list_releases__get_all_releases_without_offset__success(mocker):
    queue_mocker = mocker.patch("exporter.helper.queue.Queue")
    exit_event_mocker = mocker.patch("exporter.helper.threading.Event")
    mock_stdout = MagicMock()
    result = {
        "Releases": [
            {"Name": "release-1", "Namespace": "release-1", "Updated": ""},
            {"Name": "release-2", "Namespace": "release-2", "Updated": ""},
            {"Name": "release-3", "Namespace": "release-3", "Updated": ""},
        ]
    }
    mock_stdout.configure_mock(**{"stdout.decode.return_value": str(result)})

    sub_process_mock = mocker.patch(
        "exporter.helper.subprocess.run", return_value=mock_stdout
    )

    helper.put_all_releases_in_queue(HELM_V2_BINARY, queue_mocker, exit_event_mocker)

    helm_command = [HELM_V2_BINARY, "list", "--output", "yaml"]

    sub_process_mock.assert_called_with(
        helm_command, capture_output=True, check=True, stdout=None
    )


def test_helm_get__success(mocker):
    sub_process_mock = mocker.patch("subprocess.run")

    release_name = "default"

    helper.helm_get(HELM_V2_BINARY, release_name)

    helm_command = [HELM_V2_BINARY, "get", "manifest", release_name]

    sub_process_mock.assert_called_with(
        helm_command, capture_output=True, check=True, stdout=None
    )


def test_helm_release_exists__success(mocker):
    sub_process_mock = mocker.patch("subprocess.run")

    release_name = "default"

    helper.helm_release_exists(HELM_V2_BINARY, release_name)

    helm_command = [HELM_V2_BINARY, "get", release_name]

    sub_process_mock.assert_called_with(
        helm_command, capture_output=True, check=True, stdout=None
    )


@pytest.mark.parametrize(
    ["duration", "parsed_duration"],
    [("120s", 120), ("10m", 600), ("5h", 18000), ("2d", 172_800), ("2w", 1_209_600)],
)
def test_parse_duration__success(duration, parsed_duration):
    assert helper.parse_duration(duration) == parsed_duration


def test_parse_duration__unknown_duration__raises_value_error():
    with pytest.raises(ValueError):
        helper.parse_duration("3y")
