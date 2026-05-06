import platform
from pathlib import Path
from setuptools import find_packages, setup

PACKAGE_ROOT = Path(__file__).parent


def read_requirements(name: str):
    p = PACKAGE_ROOT.joinpath(name)
    reqs = []
    for line in p.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        req = line
        req = req.split("# ")[0].strip()
        if req.startswith("file:"):
            if platform.system() == "Windows":
                continue
            relative = Path(req[len("file:") :])
            virtual = Path("localhost", PACKAGE_ROOT.relative_to("/"), relative)
            req = f"{relative.name} @ file://{virtual}"
        reqs.append(req)
    return reqs


setup(
    name="yt-da-client",
    version="0.1.0",
    packages=find_packages(),
    package_data={
        "": ["yt_da_client_example.ipynb"],
    },
    package_dir={"yt_da_client": "yt_da_client"},
    python_requires=">= 3.11",
    install_requires=read_requirements("requirements/production.txt"),
    extras_require={
        "dev": read_requirements("requirements/dev.txt"),
    },
    url="https://github.com/klipbn/ytsaurus_python_client",
    author="Alexey Voronko",
    author_email="klipefrem@gmail.com",
    description="YT Data Analysis Client",
    long_description=Path("README.md").read_text(),
    long_description_content_type="text/markdown",
    classifiers=[
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
    ],
)
