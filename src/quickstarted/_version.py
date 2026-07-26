"""Single source of the version, importable without pulling in the package.

Kept separate so low-level modules can stamp the version (User-Agent, results
schema) without a circular import through `quickstarted/__init__.py`.
"""

__version__ = "0.3.0"
