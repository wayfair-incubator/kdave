import argparse
import logging

from flask import Flask
from gevent.pywsgi import WSGIServer

from exporter.app import check_release_deprecation
from exporter.constants import HELM_V2_BINARY
from exporter.helper import helm_release_exists

app = Flask(__name__)
helm_binary = HELM_V2_BINARY
logging.basicConfig(
    format="[%(levelname)s] %(asctime)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger("kdave-service")


@app.route("/health")
def app_is_healthy():

    return "OK"


@app.route("/release/<string:release>", methods=["GET"])
def check_release(release):

    msgs = ""
    if not helm_release_exists(helm_binary, release):
        msgs = f"""
           <h1 style="color:DarkRed;"> Release Not Found:</h1>
           <h2> The release: {release} doesn't exist. </h2>
           """
        return msgs

    deprecations = check_release_deprecation(helm_binary, release)
    if not deprecations:
        msgs = f"""
           <h1 style="color:DarkGreen;"> Congratulations!</h1>
           <h2> Your release: {release} doesn't have any deprecated apiVersions </h2>
           """
    else:
        msgs = """<h1 style="color:DarkRed;">Found Deprecated apiVersions:</h1>"""
    for dep in deprecations:
        status = "removed" if dep["removed"] == "true" else "deprecated"
        msg = f'The {dep["kind"]}: {dep["name"]} uses the {status} apiVersion: {dep["api_version"]}. Use {dep["replacement_api"]} instead.'
        msgs = msgs + f"<h3>{msg}</h3>"

    return msgs


def get_arguments():
    parser = argparse.ArgumentParser()

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
    helm_binary = args.helm_binary

    app_server = WSGIServer((args.address, args.port), app)
    logger.info("Starting kdave helm releases checker service.")
    logger.info(f"Running on http://{args.address}:{args.port}/")

    app_server.serve_forever()
