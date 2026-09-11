"""
Test isolation guard.

The live application database (data/app.db) must NEVER be touched by tests.
This conftest points the entire app at a throwaway temp database BEFORE any
app module is imported. Delete this file and you risk wiping real user data.
"""
import os
import tempfile

# Must run before `app.config` is imported by test modules.
os.environ["INSTANT_ENGINE_DB_PATH"] = os.path.join(
    tempfile.gettempdir(), "instant_engine_test.db"
)

# Start every session from a clean slate.
_test_db = os.environ["INSTANT_ENGINE_DB_PATH"]
if os.path.exists(_test_db):
    os.remove(_test_db)
for _suffix in ("-wal", "-shm"):
    _side = _test_db + _suffix
    if os.path.exists(_side):
        os.remove(_side)
