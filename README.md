![CI pipeline status](https://github.com/wayfair-incubator/kdave/workflows/CI/badge.svg?branch=main)
![PyPI](https://img.shields.io/pypi/v/kdave)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/kdave)
![Checked with mypy](https://img.shields.io/badge/mypy-checked-blue)
![Code style: black](https://img.shields.io/badge/code%20style-black-black.svg)

# kdave

## Introduction

The kdave (Kubernetes Deprecated API Versions Exporter) checks for any deprecated or removed apiVersions in the cluster and exports them in a Prometheus metrics format. You can integrate it with Prometheus and Alertmanager to receive notifications before upgrading the cluster and break the current workload.
It exports detailed metrics such as whether the used apiVersion is `deprecated`, `removed`, `removed_in_next_release`, `removed_in_next_2_releases`, `replacement_api`, etc.

Kdave has a CLI to check the used Kubernetes apiVersions for different sources including files, folders, charts, releases, and namespaces. You can integrate the CLI with the CI system to check the used apiVersions in the helm chart and
return a warning message in the Pull request or fail the pipeline. You can control this behavior by changing the exit code with the command line options as explained [below](#commands-and-command-line-options)

For example, you can return a warning message in the Pull request if the helm chart has any deprecated apiVersions, the message will include the replacement apiVersion to be used. Also, you can fail the pipeline if the helm chart has any removed apiVersion or apiVersion that will be removed in the next release. This is an example of [alerting](images/alert-example.png) and [CI integration](images/ci-example-1.png)

Also, kdave has a simple web service to check the used apiVersions for a specific release in a real-time. This can be used if the developers don't have permission to run helm commands and thus can't use kdave CLI.

## Purpose

Kubernetes is a REST API driven system with a lot of features that evolve over time. When new features are introduced, Kubernetes might deprecate or remove apiVersions. More information can be found in the Kubernetes deprecation [policy](https://kubernetes.io/docs/reference/using-api/deprecation-policy/)

The kdave server checks for any deprecated or removed apiVersions in the deployed helm releases. This means that it checks only for the objects deployed by helm.
The reason for using helm releases as the source is that the Kubernetes API doesn't return the real apiVersion of the object. It returns the best apiVersion based on `versionPriority`

Also, if you requested the object from the API server on a specific apiVersion, it'll return it as long as it's supported. For example, if you have a deployment with apiVersion `apps/v1beta2`, the API server will return this deployment if you requested it with another apiVersion `kubectl get deployments.v1beta1.extensions nginx`. More details can be found in this [issue](https://github.com/kubernetes/kubernetes/issues/58131#issuecomment-356823588)

## Usage

### Deployment

`kdave` can be run as a deployment in the cluster using the latest server docker image `aelbakry/kdave-server`. See `kdave` helm [chart](https://github.com/amelbakry/kdave-chart)

`kdave-server` can be configured via command line arguments. These arguments are also available in the helm chart

#### Available server command line options

``--address``
    The IP address for the Flask server to serve on

``--port``
    The Port for the Flask server to serve on

``--threads``
    The number of threads to handle helm check releases

``--max``
    Maximum number of releases to fetch

``--interval``
    The interval between helm check releases jobs. Accepted suffix (s, m, h, d, w). Default is (1d)"

``--delay``
    The accepted helm check releases job delay. Accepted suffix (s, m, h, d, w). Default is (2h)"

``--data-file``
    The database file location

``--helm-binary``
    The helm binary to be used for running helm commands. Default is helm v2. Options: helm or helm3

### Using the CLI

`kdave` CLI is available as a python package and docker image.

#### Using the python package

There are a few requirements when using the Python package

* Helm client should be installed and exists in the path ($PATH).
* Copy `versions.yaml` in the config folder to `~/.kdave`

```bash
pip3 install kdave
kdave --help

```

#### Using the docker image

```bash
docker run --rm -v ~/.kube/config:/home/app/.kube/config aelbakry/kdave:latest --help
```

#### Commands and Command Line Options

**Available commands**:

``check``
    Check deprecated or removed apiVersions for different sources

**Available command line options**:

``--source``
    The full path of a file or directory

``--chart``
    The full path of a chart

``--release``
    The name of the release

``--namespace``
    The name of the namespace

``--tabulate``
    Print output in table format

``--message``
    Print a recommendation message with the replacement apiVersion

``--version``
    The Kubernetes version. If not provided, it defaults to the current cluster version

``--helm-binary``
    The helm binary to be used for running helm commands. Default is helm v2

``--output-dir``
    The output directory used to template the chart

``--values``
    The values file used to template the chart

``--format``
    Format the message based on its severity

``--skip-dependencies``
    Skip building dependencies for the given chart. You can skip it if dependencies already exist in charts/ folder

``--deprecated-apis-exit-code``
    Deprecated API versions exit code

``--removed-apis-exit-code``
    Removed API versions exit code

``--removed-apis-in-next-release-exit-code``
    Removed API versions in next release exit code

#### Examples

```bash
$ kdave check --release ingress
[INFO] 2021-07-12 14:22:58 Calling the helm command: [helm get manifest ingress]
[INFO] 2021-07-12 14:23:03 Checking the used apiVersions for release: ingress
 Checking the used apiVersions:
+---------------+--------------------+-----------------------------------+---------------------------------+-------------+----------+------------------------+---------------------+------------------------------+
|  Release name |  Kind              |  API Version                      |  Name                           |  Deprecated |  Removed |  Deprecated In Version |  Removed In Version |  Replacement API             |
+---------------+--------------------+-----------------------------------+---------------------------------+-------------+----------+------------------------+---------------------+------------------------------+
| ingress       | ClusterRole        | rbac.authorization.k8s.io/v1beta1 | ingress-nginx-ingress           | true        | false    | v1.17.0                | v1.22.0             | rbac.authorization.k8s.io/v1 |
| ingress       | ClusterRoleBinding | rbac.authorization.k8s.io/v1beta1 | ingress-nginx-ingress           | true        | false    | v1.17.0                | v1.22.0             | rbac.authorization.k8s.io/v1 |
| ingress       | Role               | rbac.authorization.k8s.io/v1beta1 | ingress-nginx-ingress           | true        | false    | v1.17.0                | v1.22.0             | rbac.authorization.k8s.io/v1 |
| ingress       | RoleBinding        | rbac.authorization.k8s.io/v1beta1 | ingress-nginx-ingress           | true        | false    | v1.17.0                | v1.22.0             | rbac.authorization.k8s.io/v1 |
| ingress       | Ingress            | extensions/v1beta1                | ingress-health                  | true        | false    | v1.14.0                | v1.22.0             | networking.k8s.io/v1         |
+---------------+--------------------+-----------------------------------+---------------------------------+-------------+----------+------------------------+---------------------+------------------------------+

$ kdave check --source /tmp/metallb.yaml --message
The Deployment: metallb-controller uses the removed apiVersion: apps/v1beta2. Use apps/v1 instead.
The DaemonSet: metallb-speaker uses the removed apiVersion: apps/v1beta2. Use apps/v1 instead.
The PodSecurityPolicy: metallb-speaker uses the removed apiVersion: extensions/v1beta1. Use policy/v1beta1 instead.

$ echo $?
10
```

## How it works

`kdave-server` runs two processes. One process runs the flask server to serve the requests, and the other process `helm-checker` runs an endless loop to check the deprecated or removed apiVersions from the current deployed helm releases.

The `helm-checker` process/job is triggered by the flask process to get or update the metrics.

The `helm-checker` checks the deprecated or removed apiVersions every specific interval, configured via command line argument `--interval`, the default is 1 day. This means that the metrics will be up to one day old. Also, the metrics are saved in a data file configured via command line argument `--data-file` to keep the metrics in this data file in case of a pod restart. This design is to reduce the number of API calls which is made by helm to list all the releases and get the manifests for them.

The exported metrics have a field called `release_last_update` to let you know when the release was last updated. If the release is newer than one day (default interval), the exported metric for it maybe inaccurate and you can use the CLI to check it.

The main purpose for the exported metrics is to have visibility over the deprecated or removed apiVersions in the whole cluster or multiple clusters to take action and fix them. So, it's accepted to be old up to a specific interval in favor of reducing the number of API calls.

For more details, please check the [Design](docs/design.md) document.

## Testing

```bash
docker-compose run test
```

## Local Development

```bash
python3 -m venv /tmp/kdave-venv
source /tmp/kdave-venv/bin/activate
pip3 install -r requirements.txt 
python3 -m exporter.app 
deactivate
```

## Contributing

Contributions are what make the open source community such an amazing place to learn, inspire, and create. Any contributions you make are **greatly appreciated**. For detailed contributing guidelines, please see [CONTRIBUTING.md](CONTRIBUTING.md)

## License

Distributed under the `MIT` License. See `LICENSE` for more information.

## Contact

Ahmed ElBakry - [@ahmed43068401](https://twitter.com/ahmed43068401)

Project Link: [https://github.com/wayfair-incubator/kdave](https://github.com/wayfair-incubator/kdave)

## Acknowledgements

This template was adapted from
[https://github.com/othneildrew/Best-README-Template](https://github.com/othneildrew/Best-README-Template).
