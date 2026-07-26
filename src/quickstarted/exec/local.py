"""Unenforced local execution: a throwaway directory and a scrubbed environment.

Commands run as your user, on your filesystem, with your network. Absolute
paths reach your home directory and a command that ignores the proxy variables
reaches any host. Useful for developing journeys against your own code; wrong
for anything you did not write.
"""

from __future__ import annotations

from .base import ProcessExecutor


class LocalExecutor(ProcessExecutor):
    name = "local"
    enforced = False
