# -*- coding: utf-8 -*-

"""外向き通信の許可リスト制御（エグレスガード）

許可したホスト以外へは接続させない。名前解決の時点で遮断するため、DNS 経由の
情報持ち出しも塞ぐ。接続先 IP は「許可ホストの解決結果」または明示的に許可した
アドレスのみ通すため、IP 直打ちによる回避もできない。
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import threading
import traceback
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .network_audit import NetworkAuditLog

DEFAULT_ALLOWED_HOSTS: Tuple[str, ...] = ("www.i-ppi.jp",)
DEFAULT_AUDIT_LOG = "./logs/network.log"
LOOPBACK_HOSTNAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})


class BlockedConnectionError(OSError):
    """ポリシー違反の外向き通信をブロックしたときに送出する"""


@dataclass(frozen=True)
class NetworkPolicy:
    """外向き通信の許可リスト。allowed_hosts が空なら全遮断。"""

    allowed_hosts: Tuple[str, ...] = DEFAULT_ALLOWED_HOSTS
    allowed_ports: Tuple[int, ...] = (443,)
    allow_loopback: bool = True
    block_private_ips: bool = True
    audit_log: Optional[Path] = None

    def allows_host(self, host: str) -> bool:
        if not host:
            return False
        target = str(host).strip().rstrip(".").casefold()
        for pattern in self.allowed_hosts:
            allowed = str(pattern).strip().rstrip(".").casefold()
            if not allowed:
                continue
            if allowed.startswith("*."):
                if target == allowed[2:] or target.endswith(allowed[1:]):
                    return True
            elif target == allowed:
                return True
        return False

    def allows_port(self, port: Optional[int]) -> bool:
        if port is None:
            return True
        if not self.allowed_ports:
            return False
        return int(port) in self.allowed_ports

    @property
    def denies_everything(self) -> bool:
        return not self.allowed_hosts


def _is_loopback(ip) -> bool:
    return bool(ip.is_loopback or ip.is_unspecified)


def _is_internal(ip) -> bool:
    return bool(ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast)


def _parse_ip(value: str):
    try:
        return ipaddress.ip_address(str(value).split("%", 1)[0])
    except ValueError:
        return None


def _address_ip(address: Any) -> Optional[str]:
    if isinstance(address, tuple) and address:
        return str(address[0])
    return None


def _address_port(address: Any) -> Optional[int]:
    if isinstance(address, tuple) and len(address) > 1:
        try:
            return int(address[1])
        except (TypeError, ValueError):
            return None
    return None


def _coerce_port(port: Any) -> Optional[int]:
    if port is None or isinstance(port, str):
        return None
    try:
        return int(port)
    except (TypeError, ValueError):
        return None


def _caller() -> str:
    """呼び出し元（netguard と socket 内部を除いた最初のフレーム）"""
    for frame in reversed(traceback.extract_stack()[:-1]):
        name = Path(frame.filename).name
        if name in {"netguard.py", "socket.py", "traceback.py"}:
            continue
        return "{}:{} {}".format(name, frame.lineno, frame.name)
    return "unknown"


class _Guard:
    def __init__(self, policy: NetworkPolicy, logger: Any) -> None:
        self.policy = policy
        self.logger = logger
        self._lock = threading.Lock()
        self._resolved: Dict[str, str] = {}
        self._blocked: List[str] = []
        self._originals: Dict[str, Any] = {}

    # ----------------------------------------------------------------- 判定

    def _record_resolution(self, host: str, infos: list) -> None:
        with self._lock:
            for info in infos:
                ip = _address_ip(info[4] if len(info) > 4 else None)
                if ip:
                    self._resolved[ip] = host

    def _resolved_host(self, ip: str) -> Optional[str]:
        with self._lock:
            return self._resolved.get(ip)

    def check_host(self, host: str, port: Optional[int] = None) -> None:
        if _parse_ip(host) is not None:
            self.check_ip(host, port)
            return
        name = str(host).strip().rstrip(".").casefold()
        if name in LOOPBACK_HOSTNAMES:
            if self.policy.allow_loopback:
                return
            self._block(host, port, "ループバック通信が無効化されています")
            return
        if not self.policy.allows_host(host):
            self._block(host, port, "許可リストにないホストです")
        if not self.policy.allows_port(port):
            self._block(host, port, "許可されていないポートです")

    def check_ip(self, ip: str, port: Optional[int] = None) -> None:
        parsed = _parse_ip(ip)
        if parsed is None:
            self._block(ip, port, "宛先アドレスを解釈できません")
            return
        if _is_loopback(parsed):
            if self.policy.allow_loopback:
                return
            self._block(ip, port, "ループバック通信が無効化されています")
            return

        known = self._resolved_host(str(parsed)) is not None
        if not known and not self.policy.allows_host(ip):
            self._block(ip, port, "許可リスト外のアドレスへの直接接続です")
            return
        if self.policy.block_private_ips and _is_internal(parsed):
            self._block(ip, port, "内部ネットワーク宛の通信は禁止です")
            return
        if not self.policy.allows_port(port):
            self._block(ip, port, "許可されていないポートです")

    def _block(self, target: str, port: Optional[int], reason: str) -> None:
        caller = _caller()
        destination = "{}:{}".format(target, port) if port is not None else str(target)
        message = "通信をブロックしました: {} ({}) 呼び出し元={}".format(destination, reason, caller)
        with self._lock:
            self._blocked.append("\t".join([destination, reason, caller]))
        self.logger.warning(message)
        self.audit("blocked", destination, reason, caller)
        raise BlockedConnectionError(message)

    def audit(self, event: str, destination: str, reason: str, caller: str) -> None:
        if self.policy.audit_log is None:
            return
        writer = NetworkAuditLog(self.policy.audit_log, logger=self.logger)
        writer.write(
            event,
            destination,
            method="GUARD",
            detail="{} 呼び出し元={}".format(reason, caller) if caller else reason,
        )

    @property
    def blocked_events(self) -> List[str]:
        with self._lock:
            return list(self._blocked)

    # --------------------------------------------------------- パッチ適用

    def install(self) -> None:
        if self._originals:
            return
        guard = self

        original_getaddrinfo = socket.getaddrinfo
        original_connect = socket.socket.connect
        original_connect_ex = socket.socket.connect_ex
        original_sendto = socket.socket.sendto
        self._originals = {
            "getaddrinfo": original_getaddrinfo,
            "connect": original_connect,
            "connect_ex": original_connect_ex,
            "sendto": original_sendto,
        }

        def guarded_getaddrinfo(host, port=None, family=0, type=0, proto=0, flags=0):
            if host is not None:
                guard.check_host(str(host), _coerce_port(port))
            infos = original_getaddrinfo(host, port, family, type, proto, flags)
            if host is not None and _parse_ip(str(host)) is None:
                guard._record_resolution(str(host), list(infos))
            return infos

        def guarded_connect(self, address):
            guard._check_socket_address(self, address)
            return original_connect(self, address)

        def guarded_connect_ex(self, address):
            guard._check_socket_address(self, address)
            return original_connect_ex(self, address)

        def guarded_sendto(self, data, *args):
            address = args[-1] if args else None
            if address is not None:
                guard._check_socket_address(self, address)
            return original_sendto(self, data, *args)

        socket.getaddrinfo = guarded_getaddrinfo
        socket.socket.connect = guarded_connect
        socket.socket.connect_ex = guarded_connect_ex
        socket.socket.sendto = guarded_sendto

    def _check_socket_address(self, sock, address) -> None:
        family = getattr(sock, "family", None)
        if family not in {socket.AF_INET, socket.AF_INET6, None}:
            return
        ip = _address_ip(address)
        if ip is None:
            return
        self.check_ip(ip, _address_port(address))

    def uninstall(self) -> None:
        if not self._originals:
            return
        socket.getaddrinfo = self._originals["getaddrinfo"]
        socket.socket.connect = self._originals["connect"]
        socket.socket.connect_ex = self._originals["connect_ex"]
        socket.socket.sendto = self._originals["sendto"]
        self._originals = {}


_active: Optional[_Guard] = None
_install_lock = threading.Lock()


def _default_logger():
    return logging.getLogger("ppi_file_downloader.netguard")


def install_guard(policy: Optional[NetworkPolicy] = None, logger: Any = None) -> NetworkPolicy:
    """プロセス全体のエグレスガードを有効化する（冪等）"""
    global _active
    target_policy = policy or NetworkPolicy()
    with _install_lock:
        target_logger = logger or (_active.logger if _active else _default_logger())
        if _active is not None:
            if _active.policy == target_policy:
                _active.logger = target_logger
                return _active.policy
            _active.uninstall()
        guard = _Guard(target_policy, target_logger)
        guard.install()
        _active = guard
        return guard.policy


def install_from_config(network_config: Any, logger: Any = None) -> NetworkPolicy:
    """NetworkConfig（設定ファイル）からポリシーを組み立てて有効化する"""
    audit_log = getattr(network_config, "audit_log", None)
    policy = NetworkPolicy(
        allowed_hosts=tuple(getattr(network_config, "allowed_hosts", DEFAULT_ALLOWED_HOSTS)),
        allowed_ports=tuple(getattr(network_config, "allowed_ports", (443,))),
        block_private_ips=bool(getattr(network_config, "block_private_ips", True)),
        audit_log=Path(audit_log) if audit_log else None,
    )
    return install_guard(policy, logger=logger)


def reconfigure(
    allow_loopback: Optional[bool] = None,
    audit_log: Optional[Any] = None,
    logger: Any = None,
) -> NetworkPolicy:
    """有効なポリシーを絞り込む（許可ホストの追加はここではできない）"""
    current = current_policy() or NetworkPolicy()
    updates: Dict[str, Any] = {}
    if allow_loopback is not None:
        updates["allow_loopback"] = allow_loopback
    if audit_log is not None:
        updates["audit_log"] = Path(audit_log)
    policy = replace(current, **updates) if updates else current
    return install_guard(policy, logger=logger)


def uninstall_guard() -> None:
    global _active
    with _install_lock:
        if _active is not None:
            _active.uninstall()
            _active = None


def is_installed() -> bool:
    return _active is not None


def current_policy() -> Optional[NetworkPolicy]:
    return _active.policy if _active else None


def blocked_events() -> List[str]:
    return _active.blocked_events if _active else []


def check_host(host: str, port: Optional[int] = None) -> None:
    if _active is not None:
        _active.check_host(host, port)


def check_ip(ip: str, port: Optional[int] = None) -> None:
    if _active is not None:
        _active.check_ip(ip, port)


def audit(event: str, destination: str, reason: str = "", caller: str = "") -> None:
    """監査ログへ1行追記する（許可された通信の記録にも使う）"""
    if _active is not None:
        _active.audit(event, destination, reason, caller or _caller())
