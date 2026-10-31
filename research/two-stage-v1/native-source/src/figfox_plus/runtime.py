"""Portable local executable and browser environment selection."""
import os
import shutil
import sys


def node_command():
    """Use an explicit Node executable or resolve it from PATH."""
    command = os.environ.get('PLUS_NODE')
    if command:
        return command
    command = shutil.which('node')
    if command:
        return command
    raise RuntimeError('Node.js is required; install node on PATH or set PLUS_NODE')


def browser_environment():
    """Pass through caller configuration without host-specific defaults."""
    return os.environ.copy()


def vector_python():
    """Use the current Python unless a separate vtracer environment is selected."""
    return os.environ.get('PLUS_VECTOR_PYTHON') or sys.executable
