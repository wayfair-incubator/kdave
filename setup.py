#!/usr/bin/env python
# -*- coding: utf-8 -*-

import ast
import inspect
import os
import re

import setuptools
from setuptools import setup
from os.path import expanduser

__location__ = os.path.join(
    os.getcwd(), os.path.dirname(inspect.getfile(inspect.currentframe()))
)

_version_re = re.compile(r"__version__\s+=\s+(.*)")
with open("exporter/__init__.py", "rb") as f:
    _match = _version_re.search(f.read().decode("utf-8"))
    if _match is None:
        raise SystemExit("No version found")
    version = str(ast.literal_eval(_match.group(1)))


def get_requirements(path):
    content = open(os.path.join(__location__, path)).read()
    return [req for req in content.split("\\n") if req != ""]


def setup_package():
    setup(
        name="kdave",
        version=version,
        url="https://github.com/wayfair-incubator/kdave",
        author="Ahmed ElBakry",
        author_email="aelbakry@wayfair.com",
        description="Kubernetes deprecated API versions exporter CLI.",
        long_description=open("docs/cli.rst").read(),
        long_description_content_type="text/markdown",
        packages=setuptools.find_packages(
            exclude=["*.tests", "*.tests.*", "tests.*", "tests"]
        ),
        entry_points={
            "console_scripts": ["kdave = exporter.manage:cli",]
        },
        install_requires=get_requirements("requirements.txt"),
        classifiers=[
            "Programming Language :: Python",
            "Programming Language :: Python :: 3",
            "Programming Language :: Python :: 3.6",
            "Programming Language :: Python :: 3.7",
            "Programming Language :: Python :: 3.8",
        ],
    )


if __name__ == "__main__":
    setup_package()
