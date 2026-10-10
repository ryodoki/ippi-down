# -*- coding: utf-8 -*-

"""定期実行FIFOキューの回帰テスト。"""

from datetime import datetime, timezone
import json
import os
import threading
import time

from src.app.run_guard import RunGuard
from src.app.run_queue import QueueTicket, RunQueue
from src.app.run_queue import validate_schedule_id


class _Clock:
    def __init__(self, value: float = 0.0):
        self.value = value

    def __call__(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


class _ProcessMutex:
    def __init__(self, *, held: bool = False):
        self.held = held

    def try_acquire(self):
        if self.held:
            return None
        self.held = True
        return object()

    def release(self, token):
        assert token is not None
        self.held = False


def test_queue_times_out_after_two_hour_budget_and_removes_ticket(tmp_path):
    clock = _Clock()
    global_mutex = _ProcessMutex(held=True)
    queue = RunQueue(
        tmp_path,
        global_guard=RunGuard(process_mutex=global_mutex),
        clock=clock,
        wall_clock=clock,
        sleep=clock.sleep,
        process_alive=lambda _pid: True,
        poll_seconds=900,
    )

    with queue.wait_for_turn(
        "schedule-a",
        "run-a",
        snapshot_id="snapshot-a",
        timeout_seconds=7200,
    ) as turn:
        assert turn.acquired is False
        assert turn.reason_code == "QUEUE_TIMEOUT"
        assert turn.wait_seconds == 7200

    assert queue.list_queue() == []


def test_default_queue_is_scoped_by_install_id(tmp_path, monkeypatch):
    app_data = tmp_path / "local-app-data"
    install_root = app_data / "ippi-down"
    install_root.mkdir(parents=True)
    (install_root / "install-id").write_text(
        "install-abc\n", encoding="utf-8"
    )
    monkeypatch.setenv("LOCALAPPDATA", str(app_data))

    queue = RunQueue()

    assert queue.root == (
        install_root / "run-queue" / "install-abc"
    ).resolve(strict=False)


def test_schedule_id_contract_matches_backend_limit():
    assert validate_schedule_id("a" * 64) == "a" * 64
    for invalid in ("", "-leading", "a" * 65, "日本語"):
        try:
            validate_schedule_id(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"不正なIDを受理しました: {invalid}")


def test_queue_ticket_contains_ids_but_not_search_conditions(tmp_path):
    queue = RunQueue(tmp_path, process_alive=lambda _pid: True)
    ticket = queue._enqueue(  # noqa: SLF001 - 永続schemaの回帰確認
        "schedule-a",
        "run-a",
        snapshot_id="snapshot-a",
    )

    payload = json.loads(
        (tmp_path / f"{ticket.ticket_id}.json").read_text(encoding="utf-8")
    )

    assert payload["schedule_id"] == "schedule-a"
    assert payload["snapshot_id"] == "snapshot-a"
    assert payload["run_id"] == "run-a"
    assert "search_conditions" not in payload
    assert "config_path" not in payload


def test_dead_process_and_malformed_tickets_are_recovered(tmp_path):
    dead = QueueTicket(
        ticket_id="dead-ticket",
        run_id="dead-run",
        schedule_id="schedule-a",
        snapshot_id="snapshot-a",
        pid=999999,
        order=1,
        enqueued_at=datetime.now(timezone.utc),
    )
    (tmp_path / "dead-ticket.json").write_text(
        json.dumps(dead.to_mapping()), encoding="utf-8"
    )
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    queue = RunQueue(tmp_path, process_alive=lambda _pid: False)

    assert queue.list_queue() == []
    assert not (tmp_path / "dead-ticket.json").exists()
    assert not (tmp_path / "broken.json").exists()


def test_manual_slot_never_overtakes_a_waiting_job(tmp_path):
    global_mutex = _ProcessMutex()
    queue = RunQueue(
        tmp_path,
        global_guard=RunGuard(process_mutex=global_mutex),
        process_alive=lambda _pid: True,
    )
    queue._enqueue("schedule-a", "run-a")  # noqa: SLF001

    assert queue.has_waiting_jobs() is True
    status = queue.status_for("schedule-a")
    assert status.waiting is True
    assert status.position == 1
    assert status.total_waiting == 1
    with queue.try_acquire_manual() as acquired:
        assert acquired is False
    assert global_mutex.held is False


def test_wait_for_turn_holds_global_slot_and_cleans_ticket(tmp_path):
    global_mutex = _ProcessMutex()
    queue = RunQueue(
        tmp_path,
        global_guard=RunGuard(process_mutex=global_mutex),
        process_alive=lambda _pid: True,
    )

    with queue.wait_for_turn("schedule-a", "run-a") as turn:
        assert turn.acquired is True
        assert global_mutex.held is True
        assert queue.list_queue() == []

    assert global_mutex.held is False


def test_same_schedule_lease_rejects_duplicate_process_path(tmp_path):
    first = RunQueue(tmp_path)
    second = RunQueue(tmp_path)

    with first.schedule_lease("schedule-a") as first_acquired:
        assert first_acquired is True
        with second.schedule_lease("schedule-a") as second_acquired:
            assert second_acquired is False

    with second.schedule_lease("schedule-a") as after_release:
        assert after_release is True


def test_different_schedules_enter_global_slot_in_fifo_order(tmp_path):
    global_guard = RunGuard(process_mutex=_ProcessMutex())
    queue = RunQueue(
        tmp_path,
        global_guard=global_guard,
        process_alive=lambda _pid: True,
        poll_seconds=0.005,
    )
    entered = []

    def worker(schedule_id):
        with queue.wait_for_turn(schedule_id, f"run-{schedule_id}") as turn:
            assert turn.acquired is True
            entered.append(schedule_id)

    with global_guard.try_acquire() as blocker:
        assert blocker is True
        first = threading.Thread(target=worker, args=("schedule-a",))
        first.start()
        deadline = time.monotonic() + 2
        while queue.status_for("schedule-a").position != 1:
            assert time.monotonic() < deadline
            time.sleep(0.005)

        second = threading.Thread(target=worker, args=("schedule-b",))
        second.start()
        deadline = time.monotonic() + 2
        while queue.status_for("schedule-b").position != 2:
            assert time.monotonic() < deadline
            time.sleep(0.005)

    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert entered == ["schedule-a", "schedule-b"]


def test_detached_dispatch_ticket_survives_enqueue_process_exit(tmp_path):
    queue = RunQueue(tmp_path, process_alive=lambda _pid: False)

    ticket = queue.enqueue_dispatch_request(
        "schedule-a",
        "run-a",
        snapshot_id="snapshot-a",
        config_path=tmp_path / "snapshot.yaml",
    )

    assert ticket is not None
    queued = queue.list_queue()
    assert [item.ticket_id for item in queued] == [ticket.ticket_id]
    assert queued[0].detached is True
    assert queued[0].state == "queued"


def test_dispatcher_claims_fifo_and_reports_running_state(tmp_path):
    global_mutex = _ProcessMutex()
    queue = RunQueue(
        tmp_path,
        global_guard=RunGuard(process_mutex=global_mutex),
        process_alive=lambda _pid: True,
    )
    first = queue.enqueue_dispatch_request(
        "schedule-a",
        "run-a",
        snapshot_id="snapshot-a",
        config_path=tmp_path / "a.yaml",
    )
    second = queue.enqueue_dispatch_request(
        "schedule-b",
        "run-b",
        snapshot_id="snapshot-b",
        config_path=tmp_path / "b.yaml",
    )
    assert first is not None and second is not None

    claimed = queue.claim_next_dispatch_request()
    assert claimed is not None
    assert claimed.ticket_id == first.ticket_id
    assert claimed.state == "running"
    status = queue.status_for("schedule-a")
    assert status.running is True
    assert status.waiting is False

    with queue.dispatch_turn(claimed) as turn:
        assert turn.acquired is True
        assert global_mutex.held is True
    queue.complete_dispatch_request(claimed.ticket_id)

    next_claimed = queue.claim_next_dispatch_request()
    assert next_claimed is not None
    assert next_claimed.ticket_id == second.ticket_id


def test_dispatcher_reports_retry_waiting_and_restores_running(tmp_path):
    queue = RunQueue(tmp_path, process_alive=lambda _pid: True)
    ticket = queue.enqueue_dispatch_request(
        "schedule-a",
        "run-a",
        snapshot_id="snapshot-a",
        config_path=tmp_path / "a.yaml",
    )
    assert ticket is not None
    claimed = queue.claim_next_dispatch_request()
    assert claimed is not None

    queue.set_dispatch_state(claimed.ticket_id, "retry_waiting")
    waiting = queue.status_for("schedule-a")
    assert waiting.running is True
    assert waiting.retry_waiting is True
    assert queue.list_queue()[0].state == "retry_waiting"

    queue.set_dispatch_state(claimed.ticket_id, "running")
    running = queue.status_for("schedule-a")
    assert running.running is True
    assert running.retry_waiting is False


def test_dead_dispatcher_ticket_is_returned_to_fifo(tmp_path):
    ticket = QueueTicket(
        ticket_id="interrupted-ticket",
        run_id="run-a",
        schedule_id="schedule-a",
        snapshot_id="snapshot-a",
        pid=100,
        order=1,
        enqueued_at=datetime.now(timezone.utc),
        config_path=str(tmp_path / "snapshot.yaml"),
        detached=True,
        state="running",
        dispatcher_pid=999999,
        started_at=datetime.now(timezone.utc),
    )
    (tmp_path / "interrupted-ticket.json").write_text(
        json.dumps(ticket.to_mapping()), encoding="utf-8"
    )
    queue = RunQueue(tmp_path, process_alive=lambda _pid: False)

    recovered = queue.list_queue()

    assert len(recovered) == 1
    assert recovered[0].state == "queued"
    assert recovered[0].dispatcher_pid == 0
    assert recovered[0].started_at is None


def test_dispatch_requests_reject_duplicate_schedule_and_keep_fifo(tmp_path):
    queue = RunQueue(tmp_path, process_alive=lambda _pid: True)
    expected = []
    for index in range(20):
        schedule_id = f"schedule-{index:02d}"
        ticket = queue.enqueue_dispatch_request(
            schedule_id,
            f"run-{index:02d}",
            snapshot_id=f"snapshot-{index:02d}",
            config_path=tmp_path / f"{index:02d}.yaml",
        )
        assert ticket is not None
        expected.append(schedule_id)

    assert queue.enqueue_dispatch_request(
        "schedule-00",
        "duplicate",
        snapshot_id="other",
        config_path=tmp_path / "other.yaml",
    ) is None

    processed = []
    while True:
        ticket = queue.claim_next_dispatch_request()
        if ticket is None:
            break
        processed.append(ticket.schedule_id)
        queue.complete_dispatch_request(ticket.ticket_id)

    assert processed == expected
    assert queue.list_queue() == []


def test_old_atomic_write_temporary_file_is_swept(tmp_path):
    temporary = tmp_path / f".{('a' * 32)}-legacy.tmp"
    unrelated = tmp_path / ".unrelated.tmp"
    temporary.write_text("partial", encoding="utf-8")
    unrelated.write_text("keep", encoding="utf-8")
    old = time.time() - 3600
    os.utime(temporary, (old, old))
    os.utime(unrelated, (old, old))

    queue = RunQueue(tmp_path, process_alive=lambda _pid: True)
    assert queue.list_queue() == []
    assert not temporary.exists()
    assert unrelated.exists()


def test_owned_temporary_files_only_sweep_expired_dead_process(tmp_path):
    created = int(time.time() - 3600)
    active = tmp_path / (
        f".{('a' * 32)}-p{os.getpid()}-c{created}-x.tmp"
    )
    dead = tmp_path / (
        f".{('b' * 32)}-p999999-c{created}-x.tmp"
    )
    active.write_text("partial", encoding="utf-8")
    dead.write_text("partial", encoding="utf-8")
    old = time.time() - 3600
    os.utime(active, (old, old))
    os.utime(dead, (old, old))
    queue = RunQueue(
        tmp_path,
        process_alive=lambda pid: pid == os.getpid(),
    )

    assert queue.list_queue() == []
    assert active.exists()
    assert not dead.exists()


def test_expired_detached_ticket_is_claimed_for_timeout_recording(tmp_path):
    clock = _Clock(10_000.0)
    ticket = QueueTicket(
        ticket_id="expired-ticket",
        run_id="run-a",
        schedule_id="schedule-a",
        snapshot_id="snapshot-a",
        pid=100,
        order=1,
        enqueued_at=datetime.fromtimestamp(0, timezone.utc),
        detached=True,
    )
    (tmp_path / "expired-ticket.json").write_text(
        json.dumps(ticket.to_mapping()), encoding="utf-8"
    )
    queue = RunQueue(
        tmp_path,
        clock=clock,
        wall_clock=clock,
        sleep=clock.sleep,
        process_alive=lambda _pid: False,
    )

    claimed = queue.claim_next_dispatch_request()
    assert claimed is not None
    with queue.dispatch_turn(claimed, timeout_seconds=7200) as turn:
        assert turn.acquired is False
        assert turn.reason_code == "QUEUE_TIMEOUT"
        assert turn.wait_seconds == 10_000
