import logging

import pytest
from kubernetes.client.rest import ApiException

from exporter import app
from exporter.constants import HELM_V2_BINARY
from exporter.exceptions import (
    DeprecatedAPIVersionError,
    InvalidSemVerError,
    JobExecutionError,
    UnauthorizedError,
    versionsFileNotFoundError,
)


def test_k8s_api_initialize__success(mocker, api_mock, config_mock):
    # Patch load_incluster_config, it will not throw an exception
    load_incluster_config_mock = mocker.patch(
        "exporter.app.config.load_incluster_config"
    )

    app.k8sClient()

    # Verify that methods were called as expected
    load_incluster_config_mock.assert_called_once()
    api_mock.assert_called_once()


def test_list_namespaces__success(config_mock, api_mock):
    client = app.k8sClient()
    client.list_namespaces()
    api_mock.return_value.list_namespace.assert_called_once()


def test_get_k8s_version__success(config_mock, version_api_mock):
    client = app.k8sClient()
    client.k8s_version()
    version_api_mock.return_value.get_code.assert_called_once()


def test_get_deprecations__missing_versions_file__raises_error():
    with pytest.raises(versionsFileNotFoundError):
        app.get_all_deprecations("./missing-file.yaml")


def test_get_deprecations__success():
    kind = "Deployment"
    deprecations = app.get_all_deprecations("tests/fixtures/versions.yaml")
    assert deprecations[0]["kind"] == kind


def test_get_deprecated_versions__success(mocker):
    all_deprecated_versions = app.get_all_deprecations("tests/fixtures/versions.yaml")
    deprecated_deployment_versions = app.get_deprecated_kind_versions(
        "Deployment", all_deprecated_versions
    )
    assert isinstance(deprecated_deployment_versions, list)
    assert isinstance(deprecated_deployment_versions[0], dict)
    assert deprecated_deployment_versions[0]["kind"] == "Deployment"
    assert deprecated_deployment_versions[0]["version"] == "extensions/v1beta1"
    assert deprecated_deployment_versions[0]["replacementApi"] == "apps/v1"


def test_get_kinds_in_deprecation_file__success(mocker):
    all_deprecated_versions = app.get_all_deprecations("tests/fixtures/versions.yaml")
    kinds_in_deprecation_file = app.get_kinds_in_deprecation_file(
        all_deprecated_versions
    )
    assert isinstance(kinds_in_deprecation_file, list)
    assert "Deployment" in kinds_in_deprecation_file
    assert "DaemonSet" in kinds_in_deprecation_file
    assert "PodSecurityPolicy" in kinds_in_deprecation_file


@pytest.mark.parametrize(
    ["kind", "api_version", "k8s_version", "result"],
    [
        ("Deployment", "extensions/v1beta1", "v1.12.0", True),
        ("Deployment", "extensions/v1beta1", "v1.8.0", False),
        ("Deployment", "apps/v1beta2", "v1.10.0", True),
        ("StatefulSet", "apps/v1beta1", "v1.10.0", True),
        ("NetworkPolicy", "extensions/v1beta1", "v1.10.0", True),
        ("Ingress", "extensions/v1beta1", "v1.13.0", False),
        ("Ingress", "extensions/v1beta1", "v1.14.0", True),
        ("Ingress", "networking.k8s.io/v1beta1", "v1.19.0", True),
        ("ReplicaSet", "extensions/v1beta1", "v1.17.0", False),
        ("PriorityClass", "scheduling.k8s.io/v1beta1", "v1.17.0", True),
    ],
)
def test_is_deprecated_version__success(kind, api_version, k8s_version, result):
    all_deprecated_versions = app.get_all_deprecations("tests/fixtures/versions.yaml")
    assert (
        app.is_deprecated_version(
            kind, api_version, k8s_version, all_deprecated_versions
        )
        == result
    )


@pytest.mark.parametrize(
    ["kind", "api_version", "k8s_version", "result"],
    [
        ("Deployment", "extensions/v1beta1", "v1.12.0", False),
        ("Deployment", "apps/v1beta2", "v1.16.0", True),
        ("StatefulSet", "apps/v1beta1", "v1.16.0", True),
        ("NetworkPolicy", "extensions/v1beta1", "v1.16.0", True),
        ("NetworkPolicy", "extensions/v1beta1", "v1.15.0", False),
        ("Ingress", "extensions/v1beta1", "v1.21.0", False),
        ("Ingress", "extensions/v1beta1", "v1.22.0", True),
        ("Ingress", "networking.k8s.io/v1beta1", "v1.20.0", False),
        ("ReplicaSet", "extensions/v1beta1", "v1.17.0", True),
        ("PriorityClass", "scheduling.k8s.io/v1beta1", "v1.17.0", True),
        ("PodDisruptionBudgetList", "policy/v1beta1", "v1.17.0", False),
    ],
)
def test_is_removed_version__success(kind, api_version, k8s_version, result):
    all_deprecated_versions = app.get_all_deprecations("tests/fixtures/versions.yaml")
    assert (
        app.is_removed_version(kind, api_version, k8s_version, all_deprecated_versions)
        == result
    )


@pytest.mark.parametrize(
    ["kind", "api_version", "result"],
    [
        (
            "Deployment",
            "extensions/v1beta1",
            {
                "replacement_api": "apps/v1",
                "removed_in_version": "v1.16.0",
                "deprecated_in_version": "v1.9.0",
            },
        ),
        (
            "StatefulSet",
            "apps/v1beta1",
            {
                "replacement_api": "apps/v1",
                "removed_in_version": "v1.16.0",
                "deprecated_in_version": "v1.9.0",
            },
        ),
        (
            "PodDisruptionBudget",
            "policy/v1beta1",
            {
                "replacement_api": "n/a",
                "removed_in_version": "n/a",
                "deprecated_in_version": "v1.22.0",
            },
        ),
    ],
)
def test_get_deprecated_kind_info__success(kind, api_version, result):
    all_deprecated_versions = app.get_all_deprecations("tests/fixtures/versions.yaml")
    assert (
        app.get_deprecated_kind_info(kind, api_version, all_deprecated_versions)
        == result
    )


@pytest.mark.parametrize(
    ["version", "parsed_version"],
    [
        ("1.13.0", "1.13.0"),
        ("v1.12.0", "1.12.0"),
        ("v1.9.0-alpha.1", "1.9.0"),
        ("v1.20.0-alpha.3", "1.20.0"),
        ("v1.20.0-rc.0", "1.20.0"),
        ("v1.22.0-alpha.1", "1.22.0"),
    ],
)
def test_parse_semver__success(version, parsed_version):
    assert app.parse_semver(version) == parsed_version


@pytest.mark.parametrize(
    ["version", "steps", "incremented_version"],
    [
        ("1.13.0", 1, "1.14.0"),
        ("v1.12.0", 2, "1.14.0"),
        ("v1.9.0-alpha.1", 1, "1.10.0"),
        ("v1.20.0-alpha.3", 3, "1.23.0"),
        ("v1.20.0-rc.0", 2, "1.22.0"),
        ("v1.22.0-alpha.1", 3, "1.25.0"),
    ],
)
def test_increment_semver__success(version, steps, incremented_version):
    assert app.increment_semver(version, steps) == incremented_version


def test_parse_semver__invalid_k8s_version__raises_invalid_semver_error():
    version = "v1a.12.0"
    with pytest.raises(InvalidSemVerError):
        assert app.parse_semver(version)


def test__k8s_version__success(config_mock, version_api_mock):
    app._k8s_version()
    version_api_mock.return_value.get_code.assert_called_once()


def test__k8s_version__unauthorized__raises_unauthorized_error(
    config_mock, version_api_mock
):
    version_api_mock.return_value.get_code.side_effect = ApiException(status=401)

    with pytest.raises(UnauthorizedError):
        app._k8s_version()


@pytest.mark.parametrize(
    ["data", "k8s_version", "deprecations"],
    [
        (
            {
                "kind": "Deployment",
                "apiVersion": "extensions/v1beta1",
                "metadata": {"name": "nginx"},
            },
            "1.14.0",
            {
                "deprecated": "true",
                "removed": "false",
                "replacement_api": "apps/v1",
                "removed_in_version": "v1.16.0",
                "deprecated_in_version": "v1.9.0",
                "kind": "Deployment",
                "api_version": "extensions/v1beta1",
                "name": "nginx",
                "k8s_version": "1.14.0",
                "removed_in_next_release": "false",
                "removed_in_next_2_releases": "true",
            },
        ),
        (
            {
                "kind": "Deployment",
                "apiVersion": "apps/v1beta2",
                "metadata": {"name": "nginx"},
            },
            "v1.19.10-gke.1600",
            {
                "deprecated": "true",
                "removed": "true",
                "replacement_api": "apps/v1",
                "removed_in_version": "v1.16.0",
                "deprecated_in_version": "v1.9.0",
                "kind": "Deployment",
                "api_version": "apps/v1beta2",
                "name": "nginx",
                "k8s_version": "v1.19.10-gke.1600",
                "removed_in_next_release": "true",
                "removed_in_next_2_releases": "true",
            },
        ),
    ],
)
def test_check_deprecations__success(
    mocker, config_mock, version_api_mock, data, k8s_version, deprecations
):
    mocker.patch("exporter.app._k8s_version", return_value="v1.17.0")

    assert app.check_deprecations(data, k8s_version) == deprecations


def test_check_deprecations_in_files__yaml_with_single_document__success():
    assert app.check_deprecations_in_files(
        "tests/fixtures/single-document.yaml", "v1.16.0"
    ) == [
        {
            "deprecated": "true",
            "removed": "true",
            "replacement_api": "apps/v1",
            "removed_in_version": "v1.16.0",
            "deprecated_in_version": "v1.9.0",
            "kind": "Deployment",
            "api_version": "extensions/v1beta1",
            "name": "nginx-deployment",
            "k8s_version": "v1.16.0",
            "removed_in_next_release": "true",
            "removed_in_next_2_releases": "true",
        }
    ]


def test_check_deprecations_in_files__yaml_with_multiple_document__success():
    assert app.check_deprecations_in_files(
        "tests/fixtures/multiple-document.yaml", "v1.16.0"
    ) == [
        {
            "deprecated": "true",
            "removed": "true",
            "replacement_api": "apps/v1",
            "removed_in_version": "v1.16.0",
            "deprecated_in_version": "v1.9.0",
            "kind": "Deployment",
            "api_version": "apps/v1beta2",
            "name": "nginx-deployment",
            "k8s_version": "v1.16.0",
            "removed_in_next_release": "true",
            "removed_in_next_2_releases": "true",
        },
        {
            "deprecated": "true",
            "removed": "true",
            "replacement_api": "apps/v1",
            "removed_in_version": "v1.16.0",
            "deprecated_in_version": "v1.9.0",
            "kind": "Deployment",
            "api_version": "extensions/v1beta1",
            "name": "nginx-deployment",
            "k8s_version": "v1.16.0",
            "removed_in_next_release": "true",
            "removed_in_next_2_releases": "true",
        },
    ]


def test_get_files__return_single_file__success():
    assert app.get_files("tests/fixtures/multiple-document.yaml") == [
        "tests/fixtures/multiple-document.yaml"
    ]


def test_get_files__return_files_in_directory__success():
    files = app.get_files("tests/fixtures/dir")
    assert "tests/fixtures/dir/file-a.yaml" in files
    assert "tests/fixtures/dir/file-b.yaml" in files
    assert "tests/fixtures/dir/file-c.yaml" in files


def test_get_files__non_existing_directory__log_error_and_return_empty_list(caplog):
    with caplog.at_level(logging.DEBUG):
        app.get_files("/missing-dir")

    assert (
        "The provided path: /missing-dir doesn't exist or is not a directory."
        in caplog.text
    )
    app.get_files("/missing-dir") == []


def test_check_deprecations_all__check_file__success():
    assert app.check_deprecations_all(
        "tests/fixtures/single-document.yaml",
        HELM_V2_BINARY,
        k8s_version="1.9.0",
        tabulate=False,
    ) == [
        {
            "deprecated": "true",
            "removed": "false",
            "replacement_api": "apps/v1",
            "removed_in_version": "v1.16.0",
            "deprecated_in_version": "v1.9.0",
            "kind": "Deployment",
            "k8s_version": "1.9.0",
            "removed_in_next_release": "false",
            "removed_in_next_2_releases": "false",
            "api_version": "extensions/v1beta1",
            "name": "nginx-deployment",
            "file_name": "single-document.yaml",
        }
    ]


def test_check_deprecations_all__tabulate_output__success(mocker):
    mock_print_table_format = mocker.patch("exporter.app.print_table_format")
    app.check_deprecations_all(
        "tests/fixtures/single-document.yaml",
        HELM_V2_BINARY,
        k8s_version="1.9.0",
        tabulate=True,
    )

    mock_print_table_format.assert_called_once()


def test_check_deprecations_all__log_deprecation_message__raises_deprecation_error(
    mocker, caplog
):

    with pytest.raises(DeprecatedAPIVersionError):
        app.check_deprecations_all(
            "tests/fixtures/single-document.yaml",
            HELM_V2_BINARY,
            k8s_version="1.9.0",
            message=True,
        )


def test_check_deprecations_all__check_release__success(mocker):
    helm_template_mocker = mocker.patch("exporter.app.helm_template")
    get_files_mocker = mocker.patch("exporter.app.get_files")
    check_release_deprecation_mocker = mocker.patch(
        "exporter.app.check_release_deprecation"
    )
    app.check_deprecations_all(
        "tests/fixtures/single-document.yaml",
        HELM_V2_BINARY,
        k8s_version="1.9.0",
        release="nginx",
    )

    check_release_deprecation_mocker.assert_called_once()
    helm_template_mocker.assert_not_called()
    get_files_mocker.assert_not_called()


def test_check_deprecations_all__check_namespace_releases__success(mocker):
    helm_template_mocker = mocker.patch("exporter.app.helm_template")
    get_files_mocker = mocker.patch("exporter.app.get_files")
    check_release_deprecation_mocker = mocker.patch(
        "exporter.app.check_release_deprecation"
    )
    check_deprecation_for_releases_mocker = mocker.patch(
        "exporter.app.check_deprecation_for_namespace_releases"
    )
    app.check_deprecations_all(
        "tests/fixtures/single-document.yaml",
        HELM_V2_BINARY,
        k8s_version="1.9.0",
        namespace="nginx",
    )

    check_release_deprecation_mocker.assert_not_called()
    helm_template_mocker.assert_not_called()
    get_files_mocker.assert_not_called()
    check_deprecation_for_releases_mocker.assert_called_once()


def test_check_deprecations_all__check_chart__success(mocker):
    helm_template_mocker = mocker.patch("exporter.app.helm_template")
    get_files_mocker = mocker.patch("exporter.app.get_files")
    check_deprecation_for_releases_mocker = mocker.patch(
        "exporter.app.check_deprecation_for_namespace_releases"
    )
    check_release_deprecation_mocker = mocker.patch(
        "exporter.app.check_release_deprecation"
    )
    app.check_deprecations_all(
        "tests/fixtures/single-document.yaml",
        HELM_V2_BINARY,
        k8s_version="1.9.0",
        chart="nginx",
    )

    helm_template_mocker.assert_called_once()
    get_files_mocker.assert_called_once()
    check_release_deprecation_mocker.assert_not_called()
    check_deprecation_for_releases_mocker.assert_not_called()


def test_check_deprecation_for_releases__success(mocker):
    helm_list_namespace_releases_mocker = mocker.patch(
        "exporter.app.helm_list_namespace_releases"
    )
    get_deployed_deprecated_kinds_mocker = mocker.patch(
        "exporter.app.get_deployed_deprecated_kinds"
    )
    app.check_release_deprecation(HELM_V2_BINARY, release="nginx")

    helm_list_namespace_releases_mocker.assert_not_called()
    get_deployed_deprecated_kinds_mocker.assert_called_once()


def test_check_deprecation_for_releases__check_namespace_releases__success(mocker):
    helm_list_namespace_releases_mocker = mocker.patch(
        "exporter.app.helm_list_namespace_releases", return_value=["release"]
    )
    get_deployed_deprecated_kinds_mocker = mocker.patch(
        "exporter.app.get_deployed_deprecated_kinds"
    )
    app.check_deprecation_for_namespace_releases(HELM_V2_BINARY, namespace="default")

    helm_list_namespace_releases_mocker.assert_called_once()
    get_deployed_deprecated_kinds_mocker.assert_called_once()


def test_get_kinds_from_helm_release__success(mocker):
    helm_get_mocker = mocker.patch("exporter.app.helm_get")
    yaml_load_mocker = mocker.patch("exporter.app.yaml.safe_load_all")
    app.get_kinds_from_helm_release(HELM_V2_BINARY, "nginx")

    helm_get_mocker.assert_called_once()
    yaml_load_mocker.assert_called_once()


def test_get_deployed_deprecated_kinds__success(mocker):
    mocker.patch(
        "exporter.app.get_kinds_from_helm_release",
        return_value=[
            {
                "kind": "Deployment",
                "apiVersion": "extensions/v1beta1",
                "metadata": {"name": "nginx"},
            }
        ],
    )
    assert app.get_deployed_deprecated_kinds(
        HELM_V2_BINARY, "nginx", "default", "v1.9.0"
    ) == [
        {
            "deprecated": "true",
            "removed": "false",
            "replacement_api": "apps/v1",
            "removed_in_version": "v1.16.0",
            "deprecated_in_version": "v1.9.0",
            "kind": "Deployment",
            "api_version": "extensions/v1beta1",
            "name": "nginx",
            "release_name": "nginx",
            "namespace": "default",
            "k8s_version": "v1.9.0",
            "removed_in_next_release": "false",
            "removed_in_next_2_releases": "false",
        }
    ]


def test_get_deprecations_for_all_releases__update_existing_data__success(mocker):
    app.get_deprecations_for_all_releases(
        1,
        app.queue.Queue,
        app.threading.Event(),
        app.threading.Event(),
        HELM_V2_BINARY,
        "v1.21.0",
        app_data=app.app_data,
        lock=app.lock,
        data_file="tests/fixtures/data.json",
    )
    assert app.app_data["deprecations"] == []


def test_is_updated_data_file():
    assert app.is_updated_data_file("tests/fixtures/data.json") is True


def test_load_from_data_file__success():
    data_file = "tests/fixtures/data.json"
    all_data = app.load_from_data_file(data_file)
    assert all_data["data"] == []
    assert all_data["release_stats"] == []
    assert all_data["duration_seconds"] == 0


def test_export_deprecated_versions_metrics__success(mocker):
    mocked_queue = mocker.patch("exporter.app.queue.Queue")
    mocked_exit_event = mocker.patch("exporter.app.threading.Event")
    mocked_error_event = mocker.patch("exporter.app.threading.Event")
    mocked_lock = mocker.patch("exporter.app.manager.Lock")

    app.app_data["run_helm_update"] = True
    app.app_data["processing"] = False
    get_deprecations_for_all_releases_mocker = mocker.patch(
        "exporter.app.get_deprecations_for_all_releases"
    )
    app.export_deprecated_versions_metrics(
        1,
        mocked_queue,
        mocked_exit_event,
        mocked_error_event,
        HELM_V2_BINARY,
        "v1.21.0",
        app_data=app.app_data,
        lock=mocked_lock,
        data_file="tests/fixtures/data.json",
        run_once=True,
        max=100,
    )
    get_deprecations_for_all_releases_mocker.assert_called_with(
        1,
        mocked_queue,
        mocked_exit_event,
        mocked_error_event,
        HELM_V2_BINARY,
        "v1.21.0",
        app_data=app.app_data,
        lock=mocked_lock,
        data_file="tests/fixtures/data.json",
        max=100,
    )


def test_get_fetched_helm_data__success(mocker):
    app.app_data["last_run"] = ""
    app.get_fetched_helm_data(app_data=app.app_data, lock=app.lock)
    assert app.app_data["run_helm_update"] is True


def test_get_fetched_helm_data__is_older_than__success(mocker):
    app.app_data["run_helm_update"] = False
    mocker.patch("exporter.app.is_older_than", return_value=True)
    app.get_fetched_helm_data(app_data=app.app_data, lock=app.lock)
    assert app.app_data["run_helm_update"] is True
    assert app.app_data["deprecations"] == []


def test_get_metrics__success(mocker):
    get_fetched_helm_data_mocker = mocker.patch("exporter.app.get_fetched_helm_data")
    app.get_metrics()
    get_fetched_helm_data_mocker.assert_called_once()


def test_app_is_healthy__success(mocker):
    app.app_data["last_run"] = ""
    mocker.patch("exporter.app.is_older_than", return_value=True)
    assert app.app_is_healthy() == "OK"


def test_app_is_healthy__job_exceeded_accepted_delay__raises_job_execution_error(
    mocker
):
    app.app_data["last_run"] = "2022-01-20T00:26:25"
    mocker.patch("exporter.app.is_older_than", return_value=True)

    with pytest.raises(JobExecutionError):
        app.app_is_healthy()
