import re

DEFAULT_VERSIONS_FILE = "config/versions.yaml"
HELM_TEMPLATE_TMP_DIRECTORY = "/tmp/helm_template_tmp_dir"
HELM_V2_BINARY = "helm"
HELM_V3_BINARY = "helm3"
DATA_FILE = "data/data.json"
CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])
DEPRECATED_API_EXIT_CODE = 0
REMOVED_NEXT_RELEASE_API_EXIT_CODE = 0
REMOVED_API_EXIT_CODE = 10  # Non-zero exit code.
TIME_UNIT_TO_SECONDS = {
    "s": 1,
    "m": 60,
    "h": 60 * 60,
    "d": 60 * 60 * 24,
    "w": 60 * 60 * 24 * 7,
}
TIME_PATTERN = re.compile(r"^(\d+)([smhdw])$")
