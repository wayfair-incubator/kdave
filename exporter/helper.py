import json
import logging
import os
import queue
import shutil
import subprocess  # nosec
import sys
import threading
import time
from functools import wraps
from os.path import isdir, isfile
from pathlib import Path
from typing import Optional, TextIO

import yaml
from terminaltables import AsciiTable

from exporter.constants import (
    HELM_TEMPLATE_TMP_DIRECTORY,
    HELM_V3_BINARY,
    TIME_PATTERN,
    TIME_UNIT_TO_SECONDS,
)
from exporter.exceptions import (
    HelmChartYamlFileMissing,
    HelmCommandError,
    K8sYAMLReadError,
)

logger = logging.getLogger("exporter")


class LogFormatter(logging.Formatter):
    """Logging Formatter to add colors"""

    green = "\033[92m"
    yellow = "\x1b[33;21m"
    red = "\x1b[31;21m"
    reset = "\x1b[0m"
    _format = "%(message)s"

    FORMATS = {
        logging.INFO: green + _format + reset,
        logging.WARNING: yellow + _format + reset,
        logging.ERROR: red + _format + reset,
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


class FileHandler:
    def __init__(self, file_name):
        self.file_name = file_name

    def load(self):
        with open(self.file_name) as fd:
            data = json.load(fd)

        return data

    def save(self, data):
        with open(self.file_name, "w+") as fd:
            fd.write(data)


def applogger(app):
    logger = logging.getLogger(app)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    # create console handler with a higher log level
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(LogFormatter())
    if logger.hasHandlers():
        logger.handlers.clear()
    logger.addHandler(ch)
    return logger


def _table(func):
    def _print(*args, **kwargs):

        table_data = func(*args, **kwargs)[0]
        func(*args, **kwargs)
        title = func(*args, **kwargs)[1]
        if title:
            print("\033[1m" + " %s" % title + "\033[0m")
        table = AsciiTable(table_data)
        print(table.table)

    return _print


def load_yaml_file(file):
    try:
        with open(file) as fd:
            data = yaml.safe_load(fd)

    except EnvironmentError as e:
        raise K8sYAMLReadError(e)

    return data


def load_multiple_yaml_documents(file):
    try:
        with open(file) as fd:
            content = [data for data in yaml.safe_load_all(fd)]

    except EnvironmentError as e:
        raise K8sYAMLReadError(e)

    return content


def retry(exec=HelmCommandError, total_tries=3, delay=1, backoff_factor=2):
    def retry_decorator(func):
        @wraps(func)
        def func_with_retries(*args, **kwargs):
            _tries, _delay = total_tries + 1, delay
            while _tries > 1:
                try:
                    return func(*args, **kwargs)
                except exec as e:
                    _tries -= 1
                    if _tries == 1:
                        logger.error(
                            f"Failed to execute the function {func.__name__} after {total_tries} tries."
                        )
                        raise
                    logger.warning(
                        f"Exception when executing the function: {func.__name__}\n {e}"
                    )
                    logger.warning(f"Retrying in {_delay} seconds.")
                    time.sleep(_delay)
                    _delay *= backoff_factor

        return func_with_retries

    return retry_decorator


# Simple wrapper around subprocess
def _run_helm_command(command: list, capture_output=True):
    logger.info("Calling the helm command: [{}]".format(" ".join(command)))
    stdout: Optional[TextIO]
    if capture_output is False:
        stdout = sys.stderr
    else:
        stdout = None

    try:
        res = subprocess.run(  # nosec
            command, capture_output=capture_output, stdout=stdout, check=True
        )
    except subprocess.CalledProcessError as e:
        error_msg = "Error while executing helm command: {} \n".format(e)
        if e.stdout is not None:
            error_msg = "{}\nCaptured helm stderr: {}".format(
                error_msg, e.stdout.decode("ascii")
            )

        if e.stderr is not None:
            error_msg = "{}\nCaptured helm stderr: {}".format(
                error_msg, e.stderr.decode("ascii")
            )
        raise HelmCommandError(error_msg)

    if res.stdout is not None:
        return res.stdout.decode("utf8")
    else:
        return res.stdout


def get_chart_name(chart_path: str):
    chart_yaml = f"{chart_path}/Chart.yaml"
    if not os.path.exists(chart_yaml) or os.stat(chart_yaml).st_size == 0:
        raise HelmChartYamlFileMissing(
            f"The Chart.yaml file is missing or is empty for chart: {chart_path}"
        )

    chart_info = load_yaml_file(chart_yaml)
    return chart_info["name"]


def helm_build_dependencies(helm_binary: str, chart_path: str):
    logger.info("Updating chart dependencies")
    helm_command = [helm_binary, "dependency", "update", chart_path]
    _run_helm_command(helm_command)


def helm_template(
    chart_path: str,
    output_dir: str,
    helm_binary: str,
    values: str = None,
    custom_values: str = None,
    skip_dependencies: bool = False,
):
    values_dir = f"{chart_path}/values"
    prepare_template_tmp_dir(output_dir)

    if isfile(f"{chart_path}/requirements.yaml") and not skip_dependencies:
        helm_build_dependencies(helm_binary, chart_path)

    name = get_chart_name(chart_path)

    helm_command = [helm_binary, "template", chart_path, "--name", name]
    if custom_values:
        helm_command.extend(["--set", custom_values])
    if values:
        helm_command.extend(["--values", values, "--output-dir", output_dir])
        _run_helm_command(helm_command)

    elif isdir(values_dir):
        site_values = list(Path(values_dir).glob("**/*.yaml"))
        for val in site_values:
            instance = str(val).split("/")[-2]
            site = (str(val).split("/")[-1]).split(".")[0]
            temp_values_dir = (
                f"{output_dir}/{instance}/{site}"
                if instance != "values"
                else f"{output_dir}/{site}"
            )
            make_dir(temp_values_dir)

            helm_command_with_site_values = helm_command + [
                "--output-dir",
                temp_values_dir,
                "--values",
                str(val),
            ]
            try:
                _run_helm_command(helm_command_with_site_values)
            except HelmCommandError:
                logger.error(
                    f"Failed while templating for instance: {instance}, and site: {site}."
                )
    else:
        helm_command.extend(["--output-dir", output_dir])
        _run_helm_command(helm_command)


def prepare_template_tmp_dir(output_dir: str):
    """
    Create a temp directory to be used to template the chart.
    """
    if isdir(output_dir):
        if output_dir != HELM_TEMPLATE_TMP_DIRECTORY:
            response = input(
                f"The output directory that you provided: {output_dir} will be used to template the helm chart. \n"
                "This directory will be deleted. Press YES if you want to continue: "
            )
            if response != "YES":
                sys.exit()
        try:
            shutil.rmtree(output_dir)
        except OSError as err:
            logger.error(f"Error: {output_dir} : {err}")

    make_dir(output_dir)


def make_dir(dir_name: str):
    try:
        os.makedirs(dir_name)
    except OSError as err:
        logger.error(f"Creation of the directory {dir_name} failed: {err} \n")
        os._exit(1)


def helm_list_namespace_releases(helm_binary: str, namespace: str):
    _releases = []
    helm_command = [
        helm_binary,
        "list",
        "--namespace",
        f"{namespace}",
        "--output",
        "yaml",
    ]
    cmd = _run_helm_command(helm_command)
    releases_info = yaml.safe_load(cmd)
    if releases_info:
        releases = releases_info["Releases"]

        for release in releases:
            _releases.append(release["Name"])

    return _releases


def put_all_releases_in_queue(
    helm_binary: str, q: queue.Queue, exit_event: threading.Event, max: int = None
):
    exit_event.clear()

    all_releases = helm_list_all_releases(helm_binary, max)
    releases_info = yaml.safe_load(all_releases)
    if releases_info:
        releases = releases_info["Releases"]
        for release in releases:
            put_release_in_queue(q, release)
        next = releases_info.get("Next")
        while next:
            remaining_releases = helm_list_all_releases(helm_binary, max, next)
            next = yaml.safe_load(remaining_releases)["Next"]
            for release in yaml.safe_load(remaining_releases)["Releases"]:
                put_release_in_queue(q, release)
    while not q.empty():
        pass

    exit_event.set()


@retry(HelmCommandError, total_tries=10, delay=5)
def helm_list_all_releases(helm_binary: str, max: int = None, offset: str = None):
    releases = {}
    helm_command = [helm_binary, "list", "--output", "yaml"]
    if helm_binary == HELM_V3_BINARY:
        helm_command.extend(["--all-namespaces"])
    if max:
        helm_command.extend(["--max", str(max)])

    if offset:
        helm_command.extend(["--offset", offset])

    releases = _run_helm_command(helm_command)

    return releases


def put_release_in_queue(q: queue.Queue, release: dict):
    q.put(
        {
            "name": release["Name"],
            "namespace": release["Namespace"],
            "release_last_update": release["Updated"],
        }
    )


def helm_get(helm_binary: str, release_name: str):
    helm_command = [helm_binary, "get", "manifest", release_name]
    return _run_helm_command(helm_command)


def helm_release_exists(helm_binary: str, release_name: str) -> bool:
    helm_command = [helm_binary, "get", release_name]
    try:
        _run_helm_command(helm_command)
    except HelmCommandError:
        return False

    return True


def append_to_list(first_list: list, second_list: list):
    for item in first_list:
        if item not in second_list:
            second_list.append(item)


def parse_duration(duration: str) -> int:
    match = TIME_PATTERN.match(duration)
    if not match:
        raise ValueError(
            f'The provided duration: "{duration}" does not match format (e.g. 60s, 5m, 8h, 7d, 2w)'
        )
    value = int(match.group(1))
    unit = match.group(2)

    multiplier = TIME_UNIT_TO_SECONDS.get(unit)
    if not multiplier:
        raise ValueError(f'Unknown duration unit "{unit}" for Time "{duration}"')

    return value * multiplier
