class KubeError(Exception):
    pass


class HelmError(Exception):
    pass


class K8sYAMLReadError(KubeError):
    pass


class K8sYAMLParsingError(KubeError):
    pass


class UnauthorizedError(KubeError):
    pass


class versionsFileNotFoundError(KubeError):
    pass


class HelmCommandError(HelmError):
    pass


class DeprecatedAPIVersionError(KubeError):
    pass


class RemovedAPIVersionError(KubeError):
    pass


class RemovedNextReleaseAPIVersionError(KubeError):
    pass


class InvalidSemVerError(Exception):
    pass


class JobExecutionError(Exception):
    pass


class HelmChartYamlFileMissing(HelmError):
    pass
