import logging

import click

from exporter.app import check_deprecations_all
from exporter.constants import (
    DEPRECATED_API_EXIT_CODE,
    HELM_TEMPLATE_TMP_DIRECTORY,
    HELM_V2_BINARY,
    REMOVED_API_EXIT_CODE,
    REMOVED_NEXT_RELEASE_API_EXIT_CODE,
)
from exporter.exceptions import (
    DeprecatedAPIVersionError,
    RemovedAPIVersionError,
    RemovedNextReleaseAPIVersionError,
)


@click.group()
@click.option(
    "--debug/--no-debug", "-d", "debug", default=False, help="Enable debug output"
)
@click.pass_context
def cli(ctx, debug):

    ctx.ensure_object(dict)

    try:
        logging.basicConfig(
            format="[%(levelname)s] %(asctime)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            level=logging.DEBUG if debug else logging.INFO,
        )
    except Exception as e:
        click.echo(str(e), err=True)

    ctx.obj["debug"] = debug


@cli.command()
@click.option("--source", "-s", "source", help="The full path of a file or directory.")
@click.option("--chart", "-c", "chart", default=None, help="The full path of a chart.")
@click.option(
    "--release", "-r", "release", default=None, help="The name of the release."
)
@click.option(
    "--namespace", "-n", "namespace", default=None, help="The name of the namespace."
)
@click.option(
    "--tabulate/--no-tabulate",
    "-t",
    "tabulate",
    default=True,
    help="Print output in table format.",
)
@click.option(
    "--message/--no-message",
    "-m",
    "message",
    default=False,
    help="Print a recommendation message with the replacement apiVersion.",
)
@click.option(
    "--version",
    "-v",
    "version",
    help="The Kubernetes version. If not provided, it defaults to the current cluster version",
)
@click.option(
    "--output-dir",
    "-o",
    "output_dir",
    default=HELM_TEMPLATE_TMP_DIRECTORY,
    help="The output directory used to template the chart.",
)
@click.option(
    "--values",
    "values",
    default=None,
    help="The values file used to template the chart.",
)
@click.option(
    "--helm-binary",
    "helm_binary",
    default=HELM_V2_BINARY,
    help="The helm binary to be used for running helm commands. Default is helm v2.",
)
@click.option(
    "--custom-values",
    "custom_values",
    default=None,
    help="The custom values to be used to template the chart. You can specify multiple or separate values with commas: key1=val1,key2=val2",
)
@click.option(
    "--format/--no-format",
    "-f",
    "format",
    default=False,
    help="Format the message based on its severity.",
)
@click.option(
    "--skip-dependencies/--no-skip-dependencies",
    "-p",
    "skip_dependencies",
    default=False,
    help="Skip building dependencies for the given chart. You can skip it if dependencies already exist in charts/ folder.",
)
@click.option(
    "--deprecated-apis-exit-code",
    "deprecated_apis_exit_code",
    default=DEPRECATED_API_EXIT_CODE,
    help="Deprecated API versions exit code.",
)
@click.option(
    "--removed-apis-in-next-release-exit-code",
    "removed_apis_in_next_release_exit_code",
    default=REMOVED_NEXT_RELEASE_API_EXIT_CODE,
    help="Removed API versions in next release exit code.",
)
@click.option(
    "--removed-apis-exit-code",
    "removed_apis_exit_code",
    default=REMOVED_API_EXIT_CODE,
    help="Removed API versions exit code.",
)
@click.pass_context
def check(
    ctx,
    source,
    tabulate,
    message,
    chart,
    helm_binary,
    version,
    format,
    output_dir,
    values,
    custom_values,
    namespace,
    release,
    skip_dependencies,
    deprecated_apis_exit_code,
    removed_apis_exit_code,
    removed_apis_in_next_release_exit_code,
):
    try:
        check_deprecations_all(
            source,
            helm_binary,
            tabulate=tabulate,
            message=message,
            chart=chart,
            k8s_version=version,
            format=format,
            output_dir=output_dir,
            values=values,
            custom_values=custom_values,
            skip_dependencies=skip_dependencies,
            release=release,
            namespace=namespace,
        )
    except RemovedAPIVersionError:
        ctx.exit(removed_apis_exit_code)
    except RemovedNextReleaseAPIVersionError:
        ctx.exit(removed_apis_in_next_release_exit_code)
    except DeprecatedAPIVersionError:
        ctx.exit(deprecated_apis_exit_code)


if __name__ == "__main__":
    cli(obj={})  # pylint: disable=no-value-for-parameter,unexpected-keyword-arg
