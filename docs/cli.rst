# Kdave CLI

Kdave CLI can be used to check the used Kubernetes apiVersions for different sources including files, folders, charts, releases, and namespaces. You can integrate the CLI with the CI system to check the used apiVersions in the helm chart and
return a warning message in the Pull request or fail the pipeline. You can control this behavior by changing the exit code with the command line options as explained [below](#commands-and-command-line-options)

For example, you can return a warning message in the Pull request if the helm chart has any deprecated apiVersions, the message will include the replacement apiVersion to be used. Also, you can fail the pipeline if the helm chart has any removed apiVersion or apiVersion that will be removed in the next release.

### Using the CLI

`kdave` CLI is available as a python package and docker image.

#### Using the python package

There are a few requirements when using the Python package

* Helm client should be installed and exists in the default path ($PATH).
  - If it doesn't exist in the default path, you can use `--helm-binary` and provide the full path to the helm CLI.
* Copy `versions.yaml` in the config folder to `~/.kdave`

```
$ pip3 install kdave
$ kdave --help

```

#### Using the docker image

```
$ docker run --rm -v ~/.kube/config:/home/app/.kube/config aelbakry/kdave:latest --help
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

```
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