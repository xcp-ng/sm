from sm_typing import Any, Callable, Dict, Optional, override

import contextlib
import os
import socket
import inspect
import time

SOCKDIR = "/run/fairlock"
START_SERVICE_TIMEOUT_SECS = 2

class SingletonWithArgs(type):
    _instances: Dict[Any, Any] = {}
    _init: Dict[type, Optional[Callable[..., None]]] = {}

    def __init__(cls, name, bases, dct):
        cls._init[cls] = dct.get('__init__', None)

    @override
    def __call__(cls, *args, **kwargs) -> Any:
        init = cls._init[cls]
        if init is not None:
            key: Any = (cls, frozenset(
                    inspect.getcallargs(init, None, *args, **kwargs).items()))
        else:
            key = cls

        if key not in cls._instances:
            cls._instances[key] = super(SingletonWithArgs, cls).__call__(*args, **kwargs)
        return cls._instances[key]

class FairlockDeadlock(Exception):
    pass

class FairlockServiceTimeout(Exception):
    pass

class _FairlockImpl(metaclass=SingletonWithArgs):
    # Names currently held by this process, whatever the mode: re-entering a
    # lock is a deadlock even for readers.
    _held: Dict[str, "_FairlockImpl"] = {}

    def __init__(self, name, shared=False):
        self.name = name
        self.shared = shared
        self.sockname = os.path.join(SOCKDIR, name)
        self.sock = None

    def _ensure_service(self):
        service=f"fairlock@{self.name}.service"
        os.system(f"/usr/bin/systemctl start {service}")
        timeout = time.time() + START_SERVICE_TIMEOUT_SECS
        time.sleep(0.1)
        while os.system(f"/usr/bin/systemctl --quiet is-active {service}") != 0:
            time.sleep(0.1)
            if time.time() > timeout:
                raise FairlockServiceTimeout(f"Timed out starting service {service}")

    def _close_socket(self):
        if self.sock is None:
            return

        sock = self.sock
        self.sock = None
        with contextlib.suppress(Exception):
            sock.close()

    def _connect_and_recv(self):
        while True:
            self._close_socket()
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.setblocking(True)
            self.sock.connect(self.sockname)
            try:
                self.sock.sendall(b'R' if self.shared else b'W')
                # Merely being connected is not enough. Read a small blob of data.
                # If we got a zero-length return: it means the fairlock service exited while we
                # were waiting.
                if self.sock.recv(10):
                    self.sock.sendall(f'{os.getpid()} - {time.monotonic()}'.encode())
                    return True
            except (BrokenPipeError, ConnectionResetError):
                pass
            self._ensure_service()

    def _release(self):
        try:
            self._close_socket()
        finally:
            if _FairlockImpl._held.get(self.name) is self:
                del _FairlockImpl._held[self.name]

    def __enter__(self):
        holder = _FairlockImpl._held.get(self.name)
        if holder is not None and holder.sock is not None:
            raise FairlockDeadlock(f"Deadlock on Fairlock resource '{self.name}'")

        _FairlockImpl._held[self.name] = self
        try:
            try:
                self._connect_and_recv()
            except (FileNotFoundError, ConnectionRefusedError):
                self._ensure_service()
                self._connect_and_recv()
            return self
        except:
            self._release()
            raise

    def __exit__(self, type, value, traceback):
        self._release()
        return False

class FairlockRead(_FairlockImpl):
    """
    Shared lock: readers run together, queued FIFO behind any waiting writer.
    """

    def __init__(self, name):
        super().__init__(name, shared=True)

class FairlockWrite(_FairlockImpl):
    """
    Exclusive lock: nobody else holds the lock, readers included.
    """

    def __init__(self, name):
        super().__init__(name, shared=False)
