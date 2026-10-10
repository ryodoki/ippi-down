# -*- coding: utf-8 -*-

"""プロセス内実行ロックの回帰テスト。"""

from src.app.run_guard import RunGuard


class _FakeProcessMutex:
    def __init__(self):
        self.held = False
        self.released = 0

    def try_acquire(self):
        if self.held:
            return None
        self.held = True
        return object()

    def release(self, token):
        assert token is not None
        self.held = False
        self.released += 1


def test_run_guard_rejects_overlapping_execution():
    guard = RunGuard()

    with guard.try_acquire() as first:
        assert first is True
        with guard.try_acquire() as second:
            assert second is False

    with guard.try_acquire() as after_release:
        assert after_release is True


def test_run_guard_rejects_overlap_across_guard_instances():
    process_mutex = _FakeProcessMutex()
    first_guard = RunGuard(process_mutex=process_mutex)
    second_guard = RunGuard(process_mutex=process_mutex)

    with first_guard.try_acquire() as first:
        assert first is True
        with second_guard.try_acquire() as second:
            assert second is False

    with second_guard.try_acquire() as after_release:
        assert after_release is True

    assert process_mutex.released == 2


def test_run_guard_fails_closed_if_process_mutex_is_unavailable():
    class BrokenMutex:
        def try_acquire(self):
            raise OSError("mutex unavailable")

        def release(self, token):
            raise AssertionError("取得できていないtokenを解放してはいけない")

    guard = RunGuard(process_mutex=BrokenMutex())

    with guard.try_acquire() as acquired:
        assert acquired is False
    # ローカルロックが確実に戻ることも確認する。
    with guard.try_acquire() as acquired_again:
        assert acquired_again is False
