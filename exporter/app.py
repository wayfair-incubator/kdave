import argparse
import json
import logging
import multiprocessing
import os
import os.path
import queue
import re
import threading
import time
from datetime import datetime
from multiprocessing import Manager
from os.path import isdir, isfile
from typing import Dict, List

import semver
import yaml
from flask import Flask, Response
from gevent.pywsgi import WSGIServer
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from prometheus_client import Gauge, Info, generate_latest
from prometheus_client.core import CollectorRegistry

from exporter.constants import (
    DATA_FILE,
    DEFAULT_VERSIONS_FILE,
    HELM_TEMPLATE_TMP_DIRECTORY,
    HELM_V2_BINARY,
)
from exporter.exceptions import (
    DeprecatedAPIVersionError,
    HelmCommandError,
    InvalidSemVerError,
    JobExecutionError,
    RemovedAPIVersionError,
    RemovedNextReleaseAPIVersionError,
    UnauthorizedError,
    versionsFileNotFoundError,
)
from exporter.helper import (
    FileHandler,
    _table,
    append_to_list,
    applogger,
    helm_get,
    helm_list_namespace_releases,
    helm_template,
    load_multiple_yaml_documents,
    load_yaml_file,
    parse_duration,
    put_all_releases_in_queue,
)

app = Flask(__name__)
logger = logging.getLogger("exporter")
# Declaring some global variables that are shared among processes.
manager = Manager()
lock = manager.Lock()
interval = "1d"
delay = "2h"
app_data: dict = manager.dict(  # type: ignore
    processing=False,
    run_helm_update=False,
    deprecations=[],
    release_stats=[],
    last_run="",
    duration_seconds="",
    number_deployed_releases=0,
    number_releases_with_deprecated_api_versions=0,
    number_releases_with_removed_api_versions=0,
)


class k8sClient:
    def __init__(self):
        """
        Initialize connection to Kubernetes
        """
        try:
            config.load_incluster_config()
        except config.config_exception.ConfigException:
            config.load_kube_config()

        client_config = client.Configuration()
        self.api_client = client.api_client.ApiClient(client_config)
        self.core_api = client.CoreV1Api(self.api_client)
        self.version_api = client.VersionApi(self.api_client)

    def list_namespaces(self):
        return self.core_api.list_namespace()

    def k8s_version(self):
        return self.version_api.get_code().git_version


def _logger():
    # Multiprocessing Logger
    logger = multiprocessing.get_logger()
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "[%(asctime)s| %(levelname)s| %(processName)s] %(message)s"
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    if not len(logger.handlers):
        logger.addHandler(handler)

    return logger


def get_all_deprecations(versions_file: str = DEFAULT_VERSIONS_FILE):
    """"
    Get all the deprecated apiVersions from versions.yaml file
    """
    home_dir = os.getenv("HOME")
    versions_file = (
        f"{home_dir}/.kdave/versions.yaml"
        if os.path.exists(f"{home_dir}/.kdave/versions.yaml")
        else versions_file
    )
    if not os.path.isfile(versions_file):
        raise versionsFileNotFoundError(
            (f"Versions file: {versions_file} doesn't exist")
        )

    return load_yaml_file(versions_file)["deprecatedVersions"]


def get_deprecated_kind_versions(kind: str, all_deprecated_versions: dict):
    """
    Get all the deprecated apiVersions of specific kind such as Deployment, or DaemonSet.
    """
    deprecations = []
    for dep in all_deprecated_versions:
        if dep["kind"] == kind:
            deprecations.append(dep)

    return deprecations


def get_kinds_in_deprecation_file(deprecated_versions: dict):
    """
    Get all kinds that have deprecated apiVersions in the deprecation file "versions.yaml"
    """
    kinds: List = []
    for dep in deprecated_versions:
        if dep["kind"] not in kinds:
            kinds.append(dep["kind"])

    return kinds


def is_deprecated_version(
    kind: str, apiVersion: str, k8sVersion: str, all_deprecated_versions: dict
):
    """
    Check if the provided apiVersion of specific kind is deprecated based on the
    current k8s version and the deprecation file "versions.yaml"
    """
    deprecated_kind_versions = get_deprecated_kind_versions(
        kind, all_deprecated_versions
    )
    for deprecation in deprecated_kind_versions:
        if apiVersion == deprecation["version"]:
            if deprecation["deprecatedInVersion"] == "":
                return False
            if is_newer_or_equal_version(
                k8sVersion, deprecation["deprecatedInVersion"]
            ):
                return True

    return False


def is_removed_version(
    kind: str, apiVersion: str, k8sVersion: str, all_deprecated_versions: dict
):
    """
    Check if the provided apiVersion of specific kind is removed based on the
    current k8s version and the deprecation file "versions.yaml"
    """
    deprecated_kind_versions = get_deprecated_kind_versions(
        kind, all_deprecated_versions
    )

    for deprecation in deprecated_kind_versions:
        if apiVersion == deprecation["version"]:
            if deprecation["removedInVersion"] == "":
                return False
            if is_newer_or_equal_version(k8sVersion, deprecation["removedInVersion"]):
                return True

    return False


def get_deprecated_kind_info(kind: str, apiVersion: str, all_deprecated_versions: dict):
    """
    Get all the information about the deprecated or removed apiVersion for specific kind such as:
    replacement_api: The new apiVersion that should be used instead of the current deprecated or removed apiVersion
    deprecated_in_version: The apiVersion was deprecated in which k8s version.
    removed_in_version: The apiVersion was removed in which k8s version
    """
    result = {}

    deprecated_kind_versions = get_deprecated_kind_versions(
        kind, all_deprecated_versions
    )

    for deprecation in deprecated_kind_versions:
        if apiVersion == deprecation["version"]:
            replacement_api = (
                deprecation["replacementApi"]
                if deprecation["replacementApi"]
                else "n/a"
            )
            removed_in_version = (
                deprecation["removedInVersion"]
                if deprecation["removedInVersion"]
                else "n/a"
            )
            deprecated_in_version = (
                deprecation["deprecatedInVersion"]
                if deprecation["deprecatedInVersion"]
                else "n/a"
            )

            result["replacement_api"] = replacement_api
            result["removed_in_version"] = removed_in_version
            result["deprecated_in_version"] = deprecated_in_version

    return result


def is_newer_or_equal_version(current_k8s_version, yaml_file_version):
    """ Compare two SemVersions """
    if semver.compare(
        parse_semver(current_k8s_version), parse_semver(yaml_file_version)
    ) in [0, 1]:
        return True

    return False


def parse_semver(version: str):
    """
    Parse Semantic Version and return it in a numeric format such as 1.20.11
    For example:
    > parse_semver(v1.18.16) returns 1.18.16
    > parse_semver(v1.21.0-alpha.1) returns 1.21.0
    > parse_semver(v1.21.0-rc.0) returns 1.21.0
    If the version is not valid k8s version, it'll raise InvalidSemVerError which will be handled by other functions.
    """
    if re.match(r"(v?)(\d+\.\d+\.?\d*)(.*?)", version):
        match = re.match(r"(v?)(\d+\.\d+\.?\d*)(.*?)", version)
        return match.group(2)  # type: ignore

    else:
        raise InvalidSemVerError


def increment_semver(version: str, steps: int):
    """
    Bump the Minor version and leave other parts unchanged
    """
    ver = semver.parse_version_info(parse_semver(version))
    minor_ver = ver.minor + steps
    return f"{ver.major}.{minor_ver}.{ver.patch}"


def _k8s_version():
    """ Get current K8s version """
    client = k8sClient()
    try:
        k8s_version = client.k8s_version()
    except ApiException as e:
        if e.status == 401:
            raise UnauthorizedError

    return k8s_version


def check_deprecations(data: dict, k8s_version: str = None):
    """
    Check the deprecated apiVersions based on the current or provided K8s version
    and the source of truth yaml file "versions.yaml"
    """
    result = {}

    if not k8s_version:
        current_k8s_version = _k8s_version()

    version = k8s_version if k8s_version else current_k8s_version

    deprecations = get_all_deprecations()

    if data:
        deprecated = (
            "true"
            if is_deprecated_version(
                data["kind"], data["apiVersion"], version, deprecations
            )
            else "false"
        )
        removed = (
            "true"
            if is_removed_version(
                data["kind"], data["apiVersion"], version, deprecations
            )
            else "false"
        )

        if deprecated == "true" or removed == "true":
            deprecated_kind_info = get_deprecated_kind_info(
                data["kind"], data["apiVersion"], deprecations
            )
            result["deprecated"] = deprecated
            result["removed"] = removed
            result["replacement_api"] = deprecated_kind_info["replacement_api"]
            result["removed_in_version"] = deprecated_kind_info["removed_in_version"]
            result["deprecated_in_version"] = deprecated_kind_info[
                "deprecated_in_version"
            ]
            result["kind"] = data["kind"]
            result["api_version"] = data["apiVersion"]
            result["name"] = data["metadata"]["name"]
            result["k8s_version"] = version

            result["removed_in_next_release"] = (
                "true"
                if is_removed_version(
                    data["kind"],
                    data["apiVersion"],
                    increment_semver(version, 1),
                    deprecations,
                )
                else "false"
            )
            result["removed_in_next_2_releases"] = (
                "true"
                if is_removed_version(
                    data["kind"],
                    data["apiVersion"],
                    increment_semver(version, 2),
                    deprecations,
                )
                else "false"
            )

    return result


def check_deprecations_in_files(source: str, k8s_version: str = None):
    """
    Check the deprecated apiVersions for a yaml file or a group of yaml files. Source can be a full file path
    or a directory. Yaml file can be a single YAML document or a yaml with multiple documents
    """
    result = []

    try:
        data = load_yaml_file(source)

    except yaml.composer.ComposerError:
        data = load_multiple_yaml_documents(source)

    if isinstance(data, list):
        for dep in data:
            result.append(check_deprecations(dep, k8s_version))
    else:
        result.append(check_deprecations(data, k8s_version))

    return result


def get_files(path):
    """
    Get all the files that end with .yaml from a specific path
    """
    result = []

    if isfile(path):
        result.append(path)
        return result

    if not os.path.exists(path) or not isdir(path):
        logger.error(f"The provided path: {path} doesn't exist or is not a directory.")
        return result

    for _path, _, files in os.walk(path):

        for file in files:
            if file.endswith(".yaml"):
                result.append(os.path.join(_path, file))

    return result


def check_deprecations_all(
    source: str,
    helm_binary: str,
    k8s_version: str = None,
    message: bool = False,
    chart: str = None,
    tabulate=True,
    format: bool = False,
    output_dir: str = HELM_TEMPLATE_TMP_DIRECTORY,
    values: str = None,
    custom_values: str = None,
    skip_dependencies: bool = False,
    namespace: str = None,
    release: str = None,
):
    """
    This is the main function which calls other functions to check the deprecated apiVersions.
    It can check the deprecated apiVersions for a release, namespace, chart, directory, or file(s)
    """
    result = []

    if release:
        deprecations = check_release_deprecation(
            helm_binary, release, namespace, k8s_version
        )
        for dep in deprecations:
            result.append(dep)
    elif namespace:
        deprecations = check_deprecation_for_namespace_releases(
            helm_binary, namespace, k8s_version
        )
        for dep in deprecations:
            result.append(dep)
    elif chart:
        helm_template(
            chart, output_dir, helm_binary, values, custom_values, skip_dependencies
        )
        files = get_files(output_dir)
        result = handle_deprecation_in_files_output(k8s_version, files)  # type: ignore
    else:
        files = get_files(source)
        result = handle_deprecation_in_files_output(k8s_version, files)  # type: ignore

    if message:
        report_status(result, format)
    else:
        type = "release" if release or namespace else None
        print_table_format(result, type)

    return result


def handle_deprecation_in_files_output(k8s_version: str, files: list):
    """"
    This function handles the deprecated apiVersions result by appending the file name to the output
    """
    result: List = []
    for file in files:
        deprecations = check_deprecations_in_files(file, k8s_version)
        for dep in deprecations:
            if dep:
                file_name = file.split("/")[-1]
                dep["file_name"] = file_name
                if dep not in result:
                    result.append(dep)

    return result


def check_deprecation_for_namespace_releases(
    helm_binary: str, namespace: str, k8s_version: str = None
):
    """
    Check the deprecated apiVersions for all the releases in a namespace.
    """
    result = []

    releases = helm_list_namespace_releases(helm_binary, namespace)
    for _release in releases:
        deprecations = get_deployed_deprecated_kinds(
            helm_binary, _release, namespace, k8s_version
        )
        for dep in deprecations:
            result.append(dep)

    return result


def check_release_deprecation(
    helm_binary: str, release: str, namespace: str = None, k8s_version: str = None
):
    """
    Check the deprecated apiVersions of the deployed release.
    """
    result = []

    deprecations = get_deployed_deprecated_kinds(
        helm_binary, release, namespace, k8s_version
    )

    for dep in deprecations:
        result.append(dep)

    return result


@_table
def print_table_format(data: dict, type: str):
    """
    Print the deprecation result in a table format
    """
    msg = "Checking the used apiVersions:"
    title = [
        "Release name" if type == "release" else "File Name",
        "Kind",
        "API Version",
        "Name",
        "Deprecated",
        "Removed",
        "Deprecated In Version",
        "Removed In Version",
        "Replacement API",
    ]
    table_data = [["\033[1m" + " %s" % word + "\033[0m" for word in title]]

    for d in data:
        table_data.append(
            [
                d["release_name"] if type == "release" else d["file_name"],
                d["kind"],
                d["api_version"],
                d["name"],
                d["deprecated"],
                d["removed"],
                d["deprecated_in_version"],
                d["removed_in_version"],
                d["replacement_api"],
            ]
        )

    return table_data, msg


def report_status(deprecations: List[Dict], format: bool = False):
    _logger = applogger("exporter")
    for dep in deprecations:
        status = "removed" if dep["removed"] == "true" else "deprecated"
        msg = f'The {dep["kind"]}: {dep["name"]} uses the {status} apiVersion: {dep["api_version"]}. Use {dep["replacement_api"]} instead.'
        if format:
            _logger.warning(msg) if status == "deprecated" else _logger.error(msg)
        else:
            print(msg)

    if deprecations:
        raise_api_versions_exception(deprecations)


def raise_api_versions_exception(deprecations: List[Dict]) -> None:
    """
    This function raises an exception depending on the current deprecation status.
    This exception will be handled later to set the Exit Code.
    """
    status = set()

    for dep in deprecations:
        if dep["removed"] == "true":
            status.add("removed")
        if dep["removed_in_next_release"] == "true":
            status.add("removed_in_next_release")
        if dep["deprecated"] == "true":
            status.add("deprecated")

    if "removed" in status:
        raise RemovedAPIVersionError
    if "removed_in_next_release" in status:
        raise RemovedNextReleaseAPIVersionError
    if "deprecated" in status:
        raise DeprecatedAPIVersionError


def get_kinds_from_helm_release(helm_binary: str, release_name: str):
    """
    Get all kinds from a helm release a long with the apiVersions to check the deprection
    """
    result: List = []
    try:
        release_info = helm_get(helm_binary, release_name)
    except HelmCommandError:
        logger.warning(f"release: {release_name} not found.")
        return result

    try:
        content = [data for data in yaml.safe_load_all(release_info)]
    except yaml.scanner.ScannerError:
        logger.error(f"Failed to parse the yaml content for release {release_name}.")

        return result

    for _kind in content:
        if _kind:
            if "REVISION" in _kind:
                continue
            dep = {
                "kind": _kind["kind"],
                "apiVersion": _kind["apiVersion"],
                "metadata": {"name": _kind["metadata"]["name"]},
            }
            result.append(dep)

    return result


def get_deployed_deprecated_kinds(
    helm_binary: str, release_name: str, namespace: str = None, k8s_version: str = None
):
    """
    Get the deprecated apiVersions for the deployed kinds which are fetched from a helm release.
    """
    result: List = []
    kinds = get_kinds_from_helm_release(helm_binary, release_name)

    if not kinds:
        return result

    logger.info(f"Checking the used apiVersions for release: {release_name}")
    for _kind in kinds:
        dep = check_deprecations(_kind, k8s_version)
        if dep:
            dep["release_name"] = release_name
            dep["namespace"] = namespace if namespace else release_name
            result.append(dep)

    return result


def handle_release_deprecation(
    q: queue.Queue,
    exit_event: threading.Event,
    lock: threading.Lock,
    helm_binary: str,
    data: list,
    release_stats: list,
):
    result = []
    releases = []

    while not exit_event.is_set():
        try:
            release_info = q.get_nowait()
            deprecated_kinds = get_deployed_deprecated_kinds(
                helm_binary,
                release_info["name"],
                release_info["namespace"],
                k8s_version=None,
            )
            deprecated = "false"
            removed = "false"

            for dep in deprecated_kinds:
                if dep["deprecated"] == "true":
                    deprecated = "true"
                if dep["removed"] == "true":
                    removed = "true"

            releases.append(
                {
                    "release_name": release_info["name"],
                    "has_deprecated_api_versions": deprecated,
                    "has_removed_api_versions": removed,
                }
            )

            for dep in deprecated_kinds:
                dep["release_last_update"] = release_info["release_last_update"]

                result.append(dep)
        except queue.Empty:
            pass

    with lock:
        append_to_list(result, data)
        append_to_list(releases, release_stats)


def is_updated_data_file(data_file: str = DATA_FILE):
    file = FileHandler(data_file)
    if os.path.exists(data_file) and not os.stat(data_file).st_size == 0:
        saved_data = file.load()
        if not is_older_than(interval, datetime.fromisoformat(saved_data["last_run"])):
            return True

    return False


def get_deprecations_for_all_releases(
    threads: int,
    q: queue.Queue,
    exit_event: threading.Event,
    helm_binary: str,
    app_data=app_data,
    lock=lock,
    data_file: str = DATA_FILE,
    max: int = None,
):

    set_trigger_flag(lock, app_data=app_data)

    if is_updated_data_file(data_file):
        all_data = load_from_data_file(data_file)

        data = all_data["data"]
        release_stats = all_data["release_stats"]
        duration_seconds = all_data["duration_seconds"]

    else:
        data = []
        release_stats = []
        _lock = threading.Lock()
        start = time.time()

        put_releases_in_queue = threading.Thread(
            target=put_all_releases_in_queue,
            name="put_releases_in_queue",
            daemon=True,
            kwargs={
                "helm_binary": helm_binary,
                "q": q,
                "exit_event": exit_event,
                "max": max,
            },
        )

        put_releases_in_queue.start()

        release_checker_threads = []

        for i in range(threads):
            release_checker = threading.Thread(
                name=f"release-checker-{i}",
                daemon=True,
                target=handle_release_deprecation,
                kwargs={
                    "q": q,
                    "exit_event": exit_event,
                    "lock": _lock,
                    "helm_binary": helm_binary,
                    "data": data,
                    "release_stats": release_stats,
                },
            )
            release_checker.start()
            release_checker_threads.append(release_checker)

        for thread in release_checker_threads:
            thread.join()

        put_releases_in_queue.join()
        end = time.time()
        duration_seconds = int(end - start)

    update_global_app_data(
        data,
        release_stats,
        len(release_stats),
        get_number_of_releases(release_stats, "has_deprecated_api_versions"),
        get_number_of_releases(release_stats, "has_removed_api_versions"),
        duration_seconds,
        lock=lock,
        app_data=app_data,
    )

    if not is_updated_data_file(data_file):
        update_data_file(data_file, app_data=app_data)


def load_from_data_file(data_file: str = DATA_FILE):
    file = FileHandler(data_file)
    logger.info(f"Loading data from data file: {data_file}")
    all_data = {}
    all_data["data"] = file.load()["deprecations"]
    all_data["release_stats"] = file.load()["release_stats"]
    all_data["duration_seconds"] = file.load()["duration_seconds"]
    return all_data


def update_data_file(data_file: str = DATA_FILE, app_data=app_data):
    file = FileHandler(data_file)
    logger.info("Data file is outdated or doesn't exist. Building a new data file")
    logger.info(f"Writing data to data file: {data_file}")
    file.save(json.dumps(dict(app_data)))


def set_trigger_flag(lock=lock, app_data=app_data):
    with lock:
        app_data["processing"] = True
        app_data["run_helm_update"] = False
        app_data["last_run"] = (datetime.now()).isoformat(timespec="seconds")


def update_global_app_data(
    data,
    release_stats,
    number_deployed_releases,
    number_releases_with_deprecated_api_versions,
    number_releases_with_removed_api_versions,
    duration_seconds,
    lock=lock,
    app_data=app_data,
):
    with lock:
        app_data["deprecations"] = data
        app_data["release_stats"] = release_stats
        app_data["number_deployed_releases"] = number_deployed_releases
        app_data[
            "number_releases_with_deprecated_api_versions"
        ] = number_releases_with_deprecated_api_versions
        app_data[
            "number_releases_with_removed_api_versions"
        ] = number_releases_with_removed_api_versions
        app_data["duration_seconds"] = duration_seconds
        app_data["processing"] = False
        app_data["run_helm_update"] = False


def get_number_of_releases(releases: list, key: str) -> int:
    """
    Get number of releases that have a specific key such as "deprecated" or "removed"
    """
    total = 0
    for release in releases:
        if release[key] == "true":
            total += 1

    return total


def export_deprecated_versions_metrics(
    threads: int,
    q: queue.Queue,
    exit_event: threading.Event,
    helm_binary: str,
    app_data: dict = app_data,
    lock=lock,  # Manager.Lock
    data_file: str = DATA_FILE,
    run_once: bool = False,
    max: int = None,
):

    while True:
        time.sleep(2)
        if app_data["run_helm_update"] and not app_data["processing"]:
            logger.info("Fetching helm releases to update the current data.")
            get_deprecations_for_all_releases(
                threads,
                q,
                exit_event,
                helm_binary,
                max=max,
                app_data=app_data,
                lock=lock,
                data_file=data_file,
            )

        if run_once:
            break


def get_fetched_helm_data(app_data=app_data, lock=lock):

    if not app_data["last_run"]:
        with lock:
            app_data["run_helm_update"] = True

    elif is_older_than(interval, datetime.fromisoformat(app_data["last_run"])):
        logger.info(
            f"Data is older than {interval}, will trigger helm check releases job to update the data."
        )
        with lock:
            app_data["run_helm_update"] = True

    if not app_data["deprecations"]:
        return []

    return app_data["deprecations"]


def is_older_than(interval: str, old_date: datetime):
    try:
        time_between_dates = datetime.now() - old_date
    except TypeError:
        return False

    if time_between_dates.seconds >= parse_duration(interval):
        return True

    return False


@app.route("/health")
def app_is_healthy():
    if not app_data["last_run"]:
        logger.info("The job didn't run yet.")
        return "OK"
    accepted_delay = f"{parse_duration(delay) + parse_duration(interval)}s"
    if is_older_than(accepted_delay, datetime.fromisoformat(app_data["last_run"])):
        raise JobExecutionError(
            f"The helm check releases job didn't run for {accepted_delay}."
        )

    return "OK"


@app.route("/metrics")
def get_metrics():
    data = get_fetched_helm_data()

    wf_k8s_deprecated_versions = Info(
        name="wf_k8s_deprecated_versions",
        documentation="Deprecated API versions",
        labelnames=(
            "deprecated",
            "removed",
            "kind",
            "api_version",
            "name",
            "release_name",
            "namespace",
            "replacement_api",
            "deprecated_in_version",
            "removed_in_version",
            "release_last_update",
            "k8s_version",
            "removed_in_next_release",
            "removed_in_next_2_releases",
        ),
        registry=CollectorRegistry(),
    )
    wf_k8s_deprecated_versions_job = Info(
        name="wf_k8s_deprecated_versions_job",
        documentation="Deprecated API versions Job information",
        labelnames=("last_run", "duration_seconds"),
        registry=CollectorRegistry(),
    )
    wf_k8s_deprecated_versions_job.labels(
        app_data["last_run"], app_data["duration_seconds"]
    )

    wf_k8s_deployed_releases = Gauge(
        name="wf_k8s_deployed_releases",
        documentation="Total number of the deployed releases",
        registry=CollectorRegistry(),
    )
    wf_k8s_deployed_releases_with_deprecated_api_version = Gauge(
        name="wf_k8s_deployed_releases_with_deprecated_api_version",
        documentation="Total number of the deployed releases that have deprecated apiVersions",
        registry=CollectorRegistry(),
    )
    wf_k8s_deployed_releases_with_removed_api_version = Gauge(
        name="wf_k8s_deployed_releases_with_removed_api_version",
        documentation="Total number of the deployed releases that have removed apiVersions",
        registry=CollectorRegistry(),
    )

    wf_k8s_deployed_releases.set(app_data["number_deployed_releases"])
    wf_k8s_deployed_releases_with_deprecated_api_version.set(
        app_data["number_releases_with_deprecated_api_versions"]
    )
    wf_k8s_deployed_releases_with_removed_api_version.set(
        app_data["number_releases_with_removed_api_versions"]
    )

    for metric in data:
        wf_k8s_deprecated_versions.labels(
            metric["deprecated"],
            metric["removed"],
            metric["kind"],
            metric["api_version"],
            metric["name"],
            metric["release_name"],
            metric["namespace"],
            metric["replacement_api"],
            metric["deprecated_in_version"],
            metric["removed_in_version"],
            metric["release_last_update"],
            metric["k8s_version"],
            metric["removed_in_next_release"],
            metric["removed_in_next_2_releases"],
        )

    _metrics = (
        CollectorRegistry(),
        wf_k8s_deprecated_versions_job,
        wf_k8s_deprecated_versions,
        wf_k8s_deployed_releases,
        wf_k8s_deployed_releases_with_deprecated_api_version,
        wf_k8s_deployed_releases_with_removed_api_version,
    )

    result = ""
    for m in _metrics:
        result += generate_latest(m).decode("utf-8")

    return Response(result, mimetype="text/plain")


def get_arguments():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "-t",
        "--threads",
        help="Number of threads to handle helm check releases",
        type=int,
        default=10,
    )
    parser.add_argument(
        "-a",
        "--address",
        help="Flask IP address to listen on",
        type=str,
        default="0.0.0.0",
    )
    parser.add_argument(
        "-p", "--port", help="Flask Port to listen on.", type=int, default=8000
    )
    parser.add_argument(
        "-i",
        "--interval",
        help="Interval between helm check releases jobs. Accepted suffix (s, m, h, d, w). Default is (1d)",
        type=str,
        default="1d",
    )
    parser.add_argument(
        "-l",
        "--delay",
        help="The accepted helm check releases job delay. Accepted suffix (s, m, h, d, w). Default is (2h)",
        type=str,
        default="2h",
    )
    parser.add_argument(
        "-m", "--max", help="Maximum number of releases to fetch", type=int
    )
    parser.add_argument(
        "-d",
        "--data-file",
        help="The database file location.",
        type=str,
        default=DATA_FILE,
    )
    parser.add_argument(
        "-b",
        "--helm-binary",
        help="The helm binary to be used for running helm commands. Default is helm v2.",
        type=str,
        default=HELM_V2_BINARY,
    )
    args = parser.parse_args()

    return args


if __name__ == "__main__":
    args = get_arguments()
    interval = args.interval
    delay = args.delay
    helm_binary = args.helm_binary
    q: queue.Queue = queue.Queue()
    exit_event = threading.Event()
    logger = _logger()

    app_server = WSGIServer((args.address, args.port), app)
    logger.info("Starting kdave server.")
    logger.info(f"Running on http://{args.address}:{args.port}/")

    flask_app = multiprocessing.Process(
        name="flask-app", target=app_server.serve_forever
    )
    helm = multiprocessing.Process(
        name="helm-handler",
        target=export_deprecated_versions_metrics,
        args=(args.threads, q, exit_event, helm_binary),
        kwargs={"data_file": args.data_file, "max": args.max},
    )

    flask_app.start()
    helm.start()
    flask_app.join()
    helm.join()
