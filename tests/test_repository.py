from pathlib import Path

import pytest

from audit_ai.catalog import Catalog
from audit_ai.repository import Repository, safe_filename


def test_safe_filename_preserves_extension_and_windows_reserved_names():
    assert safe_filename("a" * 300 + ".pdf").endswith(".pdf")
    assert len(safe_filename("a" * 300 + ".pdf")) <= 180
    assert safe_filename("CON.txt").casefold() != "con.txt"
    assert safe_filename("CON.foo.txt").casefold() != "con.foo.txt"


def test_save_report_does_not_recreate_deleted_project(settings):
    catalog = Catalog(settings)
    project = catalog.create_project("Race")
    repository = Repository(settings)
    repository.ensure_project(project.id)
    repository.delete_project_files(project.id)

    with pytest.raises(FileNotFoundError):
        repository.save_report(project.id, "7ee6b958-7bf1-43ca-9040-89bf8552086e", "secret")
    assert not repository.project_dir(project.id).exists()


def test_repository_rejects_non_uuid_path_components(settings, tmp_path: Path):
    repository = Repository(settings)
    with pytest.raises(ValueError):
        repository.project_dir("../outside")
