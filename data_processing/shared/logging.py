from __future__ import annotations


def log(message: str, *, prefix: str | None = None) -> None:
    if prefix:
        print(f"[{prefix}] {message}", flush=True)
    else:
        print(message, flush=True)