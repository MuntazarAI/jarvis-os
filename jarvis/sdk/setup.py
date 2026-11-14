"""
setup.py for jarvis-sdk — Python SDK for JARVIS-OS.
"""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="jarvis-sdk",
    version="2.0.0",
    author="Muntazar Al Zaidi",
    author_email="muntazaralzaidi@users.noreply.github.com",
    description="Python SDK for JARVIS-OS — Local-First Personal AI OS",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/MuntazarAI/jarvis-os",
    packages=find_packages(where="jarvis/sdk"),
    package_dir={"": "jarvis/sdk"},
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Topic :: Software Development :: Libraries",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ],
    python_requires=">=3.10",
    install_requires=[],
    extras_require={
        "dev": ["pytest", "black", "flake8", "mypy"],
    },
    project_urls={
        "Bug Reports": "https://github.com/MuntazarAI/jarvis-os/issues",
        "Source": "https://github.com/MuntazarAI/jarvis-os",
        "Documentation": "https://muntazarai.github.io/jarvis-os/",
    },
)