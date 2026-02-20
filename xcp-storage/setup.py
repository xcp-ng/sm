#!/usr/bin/env python3
#
# Copyright (C) 2026  Vates SAS
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License

from setuptools import find_packages, setup

# ==============================================================================

setup(
    name="xcp-storage",
    version="1.0.0",
    description="XCP storage layer, scripts and plugins",
    author="Ronan Abhamon <ronan.abhamon@vates.tech>",
    author_email="ronan.abhamon@vates.tech",
    url="https://vates.tech",
    license="GPLv3",
    packages=find_packages(
        where="src",
    ),
    python_requires=">=3.6",
    package_dir={"": "src"},
    scripts=[]
)
