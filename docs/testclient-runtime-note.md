# FastAPI TestClient runtime note

## Finding

The reported `TestClient` hang is caused by the restricted validation sandbox, not by application
startup, pytest configuration, or an incompatibility among FastAPI, Starlette, and httpx.

The sandbox denies the local Unix-socket write used by `asyncio` to wake an event loop running in
another thread. Starlette's `TestClient` starts an AnyIO blocking portal in such a thread, so the
caller waits indefinitely after the denied wakeup. A direct `socket.socketpair()` reproduction
raises `PermissionError: [Errno 1] Operation not permitted` on the write. A plain `asyncio`
`call_soon_threadsafe()` reproduction hangs for the same reason and reproduces independently of
FastAPI.

Outside that restricted syscall policy, this minimal program prints `404` and exits normally:

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

app = FastAPI()
with TestClient(app) as client:
    print(client.get("/").status_code)
```

## Validated environment

- Python 3.13.16
- FastAPI 0.115.14
- Starlette 0.46.2
- httpx 0.28.1
- httpcore 1.0.9
- AnyIO 4.11.0
- pytest 9.1.1

No dependency downgrade or compatibility shim is warranted. Run the suite in a normal local,
container, or CI runtime that permits cross-thread event-loop wakeups. When diagnosing an unusually
restricted container, wrap the minimal program with a short process timeout so a denied wakeup
cannot leave the check running indefinitely.
