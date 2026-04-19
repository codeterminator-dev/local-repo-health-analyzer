from __future__ import annotations

import textwrap

from src.analyzers.python_analyzer import PythonAnalyzer
from src.parsers.pyproject_parser import PyProjectParser
from src.parsers.requirements_parser import RequirementsParser
from src.parsers.setup_py_parser import SetupPyParser


def write_file(path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


def test_requirements_parser_handles_standard_and_nonstandard_formats(tmp_path):
    write_file(
        tmp_path / "constraints.txt",
        """
        urllib3<3
        """,
    )
    write_file(
        tmp_path / "requirements-extra.txt",
        """
        pytest >= 8.0
        git+https://github.com/pallets/click.git#egg=click
        """,
    )
    write_file(
        tmp_path / "requirements.txt",
        """
        # direct dependencies
        requests >= 2.31  # inline comment
        flask[async] == 3.0.0 ; python_version >= "3.10"
        -c constraints.txt
        urllib3
        -r requirements-extra.txt
        -e ./packages/local_pkg
        """,
    )

    parser = RequirementsParser()
    result = parser.parse(tmp_path / "requirements.txt")

    dependency_map = {dependency.name: dependency for dependency in result.dependencies}
    assert dependency_map["requests"].version_spec == ">=2.31"
    assert dependency_map["flask"].version_spec == "==3.0.0"
    assert dependency_map["flask"].marker == 'python_version >= "3.10"'
    assert dependency_map["urllib3"].version_spec == "<3"
    assert dependency_map["click"].dependency_type == "vcs"
    assert dependency_map["local_pkg"].dependency_type == "path"
    assert dependency_map["local_pkg"].editable is True


def test_setup_py_parser_extracts_static_dependencies(tmp_path):
    write_file(
        tmp_path / "setup.py",
        """
        from setuptools import setup

        base_requires = ["requests>=2.31", "urllib3<3"]
        dev_requires = ["pytest>=8", "ruff==0.4.1"]

        setup(
            name="demo-package",
            install_requires=base_requires,
            extras_require={"dev": dev_requires},
            tests_require=["coverage[toml]>=7"],
        )
        """,
    )

    parser = SetupPyParser()
    result = parser.parse(tmp_path / "setup.py")

    assert result.project_name == "demo-package"
    assert sorted(dependency.name for dependency in result.dependencies) == [
        "coverage",
        "pytest",
        "requests",
        "ruff",
        "urllib3",
    ]
    dev_dependencies = [dependency for dependency in result.dependencies if dependency.name == "pytest"]
    assert dev_dependencies[0].groups == ("extra:dev",)


def test_pyproject_parser_supports_pep621_and_poetry_tables(tmp_path):
    write_file(
        tmp_path / "pyproject.toml",
        """
        [project]
        name = "root-app"
        dependencies = [
            "requests>=2.31",
            "fastapi==0.111.0",
        ]

        [project.optional-dependencies]
        dev = ["pytest>=8"]

        [tool.poetry.group.docs.dependencies]
        mkdocs = "^1.6"
        """,
    )

    parser = PyProjectParser()
    result = parser.parse(tmp_path / "pyproject.toml")

    dependency_map = {dependency.name: dependency for dependency in result.dependencies}
    assert result.project_name == "root-app"
    assert dependency_map["requests"].version_spec == ">=2.31"
    assert dependency_map["pytest"].groups == ("extra:dev",)
    assert dependency_map["mkdocs"].groups == ("group:docs",)
    assert dependency_map["mkdocs"].version_spec == "^1.6"


def test_python_analyzer_builds_transitive_dependency_graph(tmp_path):
    write_file(
        tmp_path / "pyproject.toml",
        """
        [project]
        name = "root-app"
        dependencies = ["requests>=2.31"]

        [tool.poetry.dependencies]
        local-lib = { path = "./packages/local-lib", develop = true }
        """,
    )
    write_file(
        tmp_path / "requirements.txt",
        """
        -r requirements-dev.txt
        """,
    )
    write_file(
        tmp_path / "requirements-dev.txt",
        """
        pytest>=8
        """,
    )
    write_file(
        tmp_path / "packages/local-lib/pyproject.toml",
        """
        [project]
        name = "local-lib"
        dependencies = ["urllib3<3", "idna>=3.6"]
        """,
    )

    analyzer = PythonAnalyzer()
    graph = analyzer.analyze(tmp_path)

    assert graph.has_node("root-app")
    assert graph.has_edge("root-app", "requests")
    assert graph.has_edge("root-app", "local-lib")
    assert graph.has_edge("root-app", "pytest")
    assert graph.has_edge("local-lib", "urllib3")
    assert graph.has_edge("local-lib", "idna")
    assert graph.indirect_dependencies_of("root-app") == {"urllib3", "idna"}
