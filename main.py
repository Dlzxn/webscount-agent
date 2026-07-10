"""
Единая точка входа: запускает MCP-сервер и Agent-сервер в отдельных процессах.
"""

import multiprocessing
import os
import signal
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
MCP_DIR = PROJECT_ROOT / "mcp-server"


def _run_mcp_server() -> None:
    os.chdir(MCP_DIR)
    sys.path.insert(0, str(MCP_DIR))
    import server  # noqa: F401 — запускает uvicorn


def _run_agent() -> None:
    os.chdir(PROJECT_ROOT)
    import uvicorn
    from agent.api import app

    uvicorn.run(app, host="0.0.0.0", port=8001)


def main() -> None:
    procs = {
        "mcp": multiprocessing.Process(target=_run_mcp_server, name="mcp-server", daemon=True),
        "agent": multiprocessing.Process(target=_run_agent, name="agent", daemon=True),
    }

    def _shutdown(*_: object) -> None:
        for p in procs.values():
            if p.is_alive():
                p.terminate()
        for p in procs.values():
            p.join(timeout=5)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    procs["mcp"].start()
    print("[main] MCP server starting on :8000 ...")

    # Ждём пока MCP поднимется
    for _ in range(30):
        try:
            import socket
            s = socket.socket()
            s.settimeout(1)
            s.connect(("127.0.0.1", 8000))
            s.close()
            break
        except OSError:
            time.sleep(1)
    else:
        print("[main] MCP server не поднялся за 30с, выхожу.")
        _shutdown()
        return

    print("[main] MCP server готов. Запускаю agent on :8001 ...")
    procs["agent"].start()

    try:
        for p in procs.values():
            p.join()
    except KeyboardInterrupt:
        _shutdown()


if __name__ == "__main__":
    main()
