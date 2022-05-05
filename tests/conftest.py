import pytest
from click.testing import CliRunner


@pytest.fixture()
def cli_runner(mocker) -> CliRunner:
    """
    A pytest fixture that returns a runner for testing the CLI.
    """
    return CliRunner()


@pytest.fixture
def api_mock(mocker):
    mock = mocker.patch("exporter.app.client.CoreV1Api", autospec=True)
    return mock


@pytest.fixture
def version_api_mock(mocker):
    mock = mocker.patch("exporter.app.client.VersionApi", autospec=True)
    return mock


@pytest.fixture
def config_mock(mocker):
    mock = mocker.patch("exporter.app.config")
    return mock
