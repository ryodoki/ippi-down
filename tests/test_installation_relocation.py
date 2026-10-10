# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.config.config_manager import ConfigManager
from src.models.config_model import AppConfig, ScheduleConfig
from src.scheduler.installation import (
    InstallationLocationStore,
    InstallationRelocationJournalStore,
    rebase_internal_path,
)
from src.scheduler.service import ScheduleService
from src.scheduler.task_scheduler import TaskQueryResult


JST = timezone(timedelta(hours=9))


class _TaskClient:
    def __init__(self) -> None:
        self.tasks: dict[str, str] = {}
        self.running: set[str] = set()
        self.fail_for: set[str] = set()

    def query(self, task_name: str) -> TaskQueryResult:
        xml = self.tasks.get(task_name)
        return TaskQueryResult(
            exists=xml is not None,
            running=task_name in self.running,
            xml=xml,
            enabled=True if xml is not None else None,
        )

    def query_many(self, task_names):
        return {name: self.query(name) for name in task_names}

    def create_or_update(self, task_name: str, xml: str) -> None:
        if task_name in self.fail_for:
            raise RuntimeError("registration failed")
        self.tasks[task_name] = xml

    def delete(self, task_name: str, missing_ok: bool = False) -> bool:
        return self.tasks.pop(task_name, None) is not None

    def run(self, task_name: str) -> bool:
        return task_name in self.tasks


def _service(root: Path, client: _TaskClient) -> ScheduleService:
    executable = root / "ippi-down.exe"
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(b"stub")
    namespace_path = root / "config" / "schedule-instance-id"
    namespace_path.parent.mkdir(parents=True, exist_ok=True)
    namespace_path.write_text("same-install\n", encoding="utf-8")
    return ScheduleService(
        config_dir=root / "config",
        logs_dir=root / "logs",
        install_id="same-install",
        task_client=client,
        executable=executable,
        app_root=root,
        now_provider=lambda: datetime(2026, 9, 11, 10, 0, tzinfo=JST),
        queue_ticket_provider=lambda: (),
    )


def _copied_install(tmp_path: Path, *, fail_repair: bool = False):
    old_root = tmp_path / "old-install"
    new_root = tmp_path / "new install"
    client = _TaskClient()
    old_service = _service(old_root, client)
    config = AppConfig(schedule=ScheduleConfig(enabled=True))
    config.save_paths.local = str(old_root / "downloads")
    config.logging.file = str(old_root / "logs" / "app.log")
    old_manager = ConfigManager(str(old_root / "config" / "config.yaml"))
    assert old_manager.save_config(config)
    old_status = old_service.create_schedule(
        config,
        schedule_id="roads",
        name="道路",
    )
    old_snapshot_id = str(old_status.snapshot_id)
    shutil.copytree(old_root / "config", new_root / "config")
    new_service = _service(new_root, client)
    manager = ConfigManager(str(new_root / "config" / "config.yaml"))
    loaded = manager.load_config()
    if fail_repair:
        client.fail_for.add(old_status.task_name)
    return (
        old_root,
        new_root,
        client,
        new_service,
        manager,
        loaded,
        old_status,
        old_snapshot_id,
    )


def test_existing_old_install_is_detected_and_relocated_atomically(tmp_path):
    (
        old_root,
        new_root,
        client,
        service,
        manager,
        config,
        old_status,
        old_snapshot_id,
    ) = _copied_install(tmp_path)

    preview = service.preview_installation_relocation(config)

    assert preview.required is True
    assert preview.reason_code == "INSTALLATION_PATH_CHANGED"
    assert preview.old_root == old_root.resolve()
    assert preview.current_root == new_root.resolve()
    assert preview.affected_schedule_ids == ("roads",)
    assert preview.config_changes == (
        ("save_paths.local", str(old_root / "downloads"), r".\downloads"),
        ("logging.file", str(old_root / "logs" / "app.log"), r".\logs\app.log"),
    )
    before = service.get_schedule_status("roads")
    assert before.reason_code == "INSTALLATION_PATH_CHANGED"
    assert old_root.exists()

    result = service.apply_installation_relocation(config, manager)

    assert result.success is True
    assert result.migrated_schedule_ids == ("roads",)
    assert config.save_paths.local == r".\downloads"
    assert config.logging.file == r".\logs\app.log"
    saved = manager.load_config()
    assert saved.save_paths.local == r".\downloads"
    assert saved.logging.file == r".\logs\app.log"
    registration = service.get_schedule("roads")
    assert registration is not None
    assert registration.task_name == old_status.task_name
    assert registration.command == new_root.resolve() / "ippi-down.exe"
    assert registration.working_directory == new_root.resolve()
    assert str(new_root.resolve()) in client.tasks[registration.task_name]
    assert str(old_root.resolve()) not in client.tasks[registration.task_name]

    marker = InstallationLocationStore(
        new_root / "config" / "install-location.json"
    ).read()
    assert marker is not None
    assert marker.task_namespace_id == "same-install"
    assert marker.app_root == new_root.resolve()
    old_marker = InstallationLocationStore(
        old_root / "config" / "install-location.json"
    ).read()
    assert old_marker is not None
    assert old_marker.status == "retired"
    assert old_marker.moved_to == new_root.resolve()
    registry = json.loads(
        (new_root / "config" / "schedule-registration.json").read_text(
            encoding="utf-8"
        )
    )
    entry = registry["registrations"]["roads"]
    assert old_snapshot_id in entry["relocation_archived_snapshot_ids"]
    assert (
        new_root / "config" / "schedule-profiles" / f"{old_snapshot_id}.yaml"
    ).is_file()
    assert old_root.is_dir()
    assert not service.installation_relocation_journal_path.exists()


def test_relocation_failure_restores_task_registry_and_config(tmp_path):
    (
        _old_root,
        new_root,
        client,
        service,
        manager,
        config,
        old_status,
        old_snapshot_id,
    ) = _copied_install(tmp_path, fail_repair=True)
    original_config = manager.config_path.read_bytes()
    original_registry = service.get_schedule("roads")
    original_task = client.tasks[old_status.task_name]

    result = service.apply_installation_relocation(config, manager)

    assert result.success is False
    assert result.reason_code == "TASK_REGISTER_FAILED"
    assert manager.config_path.read_bytes() == original_config
    assert service.get_schedule("roads") == original_registry
    assert client.tasks[old_status.task_name] == original_task
    assert not (new_root / "config" / "install-location.json").exists()
    assert not (
        original_registry.working_directory
        / "config"
        / "install-location.json"
    ).exists()
    assert (
        new_root / "config" / "schedule-profiles" / f"{old_snapshot_id}.yaml"
    ).is_file()
    assert not service.installation_relocation_journal_path.exists()


def test_snapshot_internal_old_paths_detect_partial_action_migration(tmp_path):
    (
        old_root,
        new_root,
        _client,
        service,
        manager,
        config,
        _old_status,
        old_snapshot_id,
    ) = _copied_install(tmp_path)
    profile = service.profile_store.get(old_snapshot_id)
    command, arguments, working_directory = service._resolve_action(
        profile.path,
        "roads",
    )
    with service.registration_store.transaction():
        document = service.registration_store.read_unlocked()
        revision = int(document["revision"])
        entry = document["registrations"]["roads"]
        entry["snapshot_path"] = str(profile.path)
        entry["command"] = str(command)
        entry["arguments"] = list(arguments)
        entry["working_directory"] = str(working_directory or "")
        service.registration_store.write_unlocked(
            document,
            expected_revision=revision,
        )
    config.save_paths.local = str(new_root / "downloads")
    assert manager.save_config(config)

    preview = service.preview_installation_relocation(config)

    assert preview.required is True
    assert preview.reason_code == "INSTALLATION_PATH_CHANGED"
    assert preview.old_root == old_root.resolve()
    assert preview.affected_schedule_ids == ("roads",)
    assert preview.config_changes == (
        ("logging.file", str(old_root / "logs" / "app.log"), r".\logs\app.log"),
    )
    changed_fields = {
        field
        for schedule_id, field, _old_value, _new_value in preview.schedule_changes
        if schedule_id == "roads"
    }
    assert changed_fields == {"save_paths.local", "logging.file"}


def test_interrupted_relocation_journal_resumes_final_commit(tmp_path):
    (
        old_root,
        new_root,
        client,
        service,
        manager,
        config,
        old_status,
        _old_snapshot_id,
    ) = _copied_install(tmp_path)
    registered_config = service.get_registered_config("roads")
    assert registered_config is not None
    registered_config.save_paths.local = r".\downloads"
    registered_config.logging.file = r".\logs\app.log"
    service.update_schedule(
        "roads",
        registered_config,
        name=old_status.name,
        expected_revision=service.get_registry().revision,
    )
    config.save_paths.local = r".\downloads"
    config.logging.file = r".\logs\app.log"
    assert manager.save_config(config)
    journal_store = InstallationRelocationJournalStore(
        service.installation_relocation_journal_path
    )
    journal_store.write("same-install", old_root, new_root)

    reopened = _service(new_root, client)
    preview = reopened.preview_installation_relocation(config)
    result = reopened.apply_installation_relocation(config, manager)

    assert preview.required is True
    assert preview.old_root == old_root.resolve()
    assert preview.affected_schedule_ids == ()
    assert result.success is True
    assert not reopened.installation_relocation_journal_path.exists()
    current_marker = InstallationLocationStore(
        new_root / "config" / "install-location.json"
    ).read()
    old_marker = InstallationLocationStore(
        old_root / "config" / "install-location.json"
    ).read()
    assert current_marker is not None
    assert current_marker.app_root == new_root.resolve()
    assert old_marker is not None
    assert old_marker.status == "retired"


def test_second_schedule_failure_rolls_back_first_schedule(tmp_path):
    old_root = tmp_path / "old-install"
    new_root = tmp_path / "new-install"
    client = _TaskClient()
    old_service = _service(old_root, client)
    main_config = AppConfig()
    main_config.save_paths.local = str(old_root / "downloads")
    main_config.logging.file = str(old_root / "logs" / "app.log")
    old_manager = ConfigManager(str(old_root / "config" / "config.yaml"))
    assert old_manager.save_config(main_config)
    for schedule_id, name in (("first", "A道路"), ("second", "B道路")):
        schedule_config = AppConfig(schedule=ScheduleConfig(enabled=True))
        schedule_config.save_paths.local = str(old_root / "downloads")
        schedule_config.logging.file = str(old_root / "logs" / "app.log")
        old_service.create_schedule(
            schedule_config,
            schedule_id=schedule_id,
            name=name,
        )
    old_registrations = {
        item.schedule_id: item for item in old_service.list_schedules()
    }
    old_tasks = dict(client.tasks)
    shutil.copytree(old_root / "config", new_root / "config")
    service = _service(new_root, client)
    manager = ConfigManager(str(new_root / "config" / "config.yaml"))
    client.fail_for.add(old_registrations["second"].task_name)

    result = service.apply_installation_relocation(
        manager.load_config(),
        manager,
    )

    assert result.success is False
    assert result.reason_code == "TASK_REGISTER_FAILED"
    assert {
        item.schedule_id: item for item in service.list_schedules()
    } == old_registrations
    assert client.tasks == old_tasks
    assert not (new_root / "config" / "install-location.json").exists()


def test_external_and_prefix_collision_paths_are_not_rebased(tmp_path):
    old_root = tmp_path / "install"
    new_root = tmp_path / "renamed install"
    external = tmp_path / "install-backup" / "downloads"

    assert rebase_internal_path(external, old_root, new_root) is None
    assert rebase_internal_path(
        old_root / "downloads",
        old_root,
        new_root,
    ) == r".\downloads"


def test_relocation_is_rejected_while_a_schedule_is_running(tmp_path):
    (
        _old_root,
        new_root,
        client,
        service,
        manager,
        config,
        old_status,
        _old_snapshot_id,
    ) = _copied_install(tmp_path)
    client.running.add(old_status.task_name)

    result = service.apply_installation_relocation(config, manager)

    assert result.success is False
    assert result.reason_code == "INSTALLATION_RELOCATION_BUSY"
    assert not (new_root / "config" / "install-location.json").exists()


def test_relocation_waits_for_other_migration_journal(tmp_path):
    (
        _old_root,
        new_root,
        _client,
        service,
        manager,
        config,
        _old_status,
        _old_snapshot_id,
    ) = _copied_install(tmp_path)
    service.migration_journal_path.write_text("{}\n", encoding="utf-8")

    result = service.apply_installation_relocation(config, manager)

    assert result.success is False
    assert result.reason_code == "MIGRATION_RECOVERY_PENDING"
    assert not (new_root / "config" / "install-location.json").exists()
    assert not service.installation_relocation_journal_path.exists()


def test_runtime_sources_do_not_pin_a_versioned_install_folder_name():
    root = Path(__file__).parents[1]
    candidates = [root / "README.md", root / "pyrightconfig.json", root / "pytest.ini"]
    for folder in ("src", "scripts", "docs", "config", ".github"):
        candidates.extend(
            path
            for path in (root / folder).rglob("*")
            if path.is_file()
            and "schedule-profiles" not in path.parts
            and path.name
            not in {
                "config.yaml",
                "install-location.json",
                "schedule-instance-id",
                "schedule-registration.json",
            }
            and path.suffix.casefold()
            in {".py", ".ps1", ".bat", ".md", ".yaml", ".yml", ".json"}
        )
    pinned = []
    for path in candidates:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"ippi-down\d", text, flags=re.IGNORECASE):
            pinned.append(str(path.relative_to(root)))

    assert pinned == []
