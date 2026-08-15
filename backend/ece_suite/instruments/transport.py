"""Transport layer: one interface, real-hardware implementation.

``Transport`` is the only thing drivers and the API see. Simulated instruments live in the
``sim`` subpackage and also implement this interface (via ``SimInstrument``), so swapping a
simulated instrument for a real one over VISA is a config change, not a rewrite.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..provenance import Provenance


class Transport(ABC):
    """Minimal message-based instrument transport."""

    #: the highest provenance data through this transport may claim
    default_provenance: Provenance = Provenance.UNVERIFIED_HW

    @abstractmethod
    def write(self, cmd: str) -> None: ...

    @abstractmethod
    def query(self, cmd: str) -> str: ...

    @abstractmethod
    def query_raw(self, cmd: str) -> bytes: ...

    def close(self) -> None:  # noqa: B027 - optional hook; most transports have nothing to close
        pass


class VisaTransport(Transport):
    """Real instrument transport over pyvisa, defaulting to the pure-Python pyvisa-py
    backend so no NI-VISA install is required. LAN (TCPIP/SOCKET) needs no extra deps;
    USB/serial/GPIB need the optional ``[hw]`` extras.
    """

    default_provenance = Provenance.UNVERIFIED_HW

    def __init__(
        self,
        resource: str,
        *,
        backend: str = "auto",
        timeout_ms: int = 5000,
        read_termination: str = "\n",
        write_termination: str = "\n",
    ):
        import threading

        import pyvisa  # lazy import so the module loads without hardware extras

        # pyvisa instrument handles are NOT thread-safe: two threads issuing write/read on the
        # same handle corrupt command/response framing. Serialize every I/O call on this
        # transport so concurrent callers (e.g. a WS stream + the chatbox/agent) can't interleave.
        self._io_lock = threading.Lock()
        self.resource = resource
        # instance-level provenance so the verification gate can promote this connection
        # to VERIFIED_HW after a successful *IDN? + read-back (sim can never be promoted).
        self.default_provenance = Provenance.UNVERIFIED_HW

        # "auto": prefer the system VISA (Keysight IO Libraries / NI-VISA), fall back to the
        # pure-Python pyvisa-py backend. This handles both USB (USBTMC) and LAN (LXI).
        candidates = ["", "@py"] if backend == "auto" else [backend]
        last_err: Exception | None = None
        self._rm = None
        for cand in candidates:
            try:
                self._rm = pyvisa.ResourceManager(cand)
                self.backend = cand or "system"
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
        if self._rm is None:
            raise RuntimeError(f"no VISA backend available: {last_err}")

        self._inst = self._rm.open_resource(resource)
        self._inst.timeout = timeout_ms
        self._inst.read_termination = read_termination
        self._inst.write_termination = write_termination

    def promote_to_verified(self) -> None:
        self.default_provenance = Provenance.VERIFIED_HW

    def write(self, cmd: str) -> None:
        with self._io_lock:
            self._inst.write(cmd)

    def query(self, cmd: str) -> str:
        with self._io_lock:                 # write+read held together: atomic query
            return self._inst.query(cmd)

    def query_raw(self, cmd: str) -> bytes:
        with self._io_lock:                 # write+read_raw held together
            self._inst.write(cmd)
            return self._inst.read_raw()

    def close(self) -> None:
        try:
            self._inst.close()
        finally:
            self._rm.close()
