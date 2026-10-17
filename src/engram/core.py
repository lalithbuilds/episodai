from pathlib import Path
import os
import threading
import sys
import math
from typing import Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor

# Linux wheels ship pysqlite3-binary because the stdlib sqlite often cannot
# load extensions (sqlite-vec) or lacks a current FTS5. Use it when present.
try:
    import pysqlite3 as sqlite3
except ImportError:
    import sqlite3

DB_PATH = os.path.join(os.path.expanduser("~"), ".engram", "engram_v3.db")
_INITIALIZED_PATHS = set()

def check_storage_liveness(path: str, timeout_seconds: float = 1.0) -> bool:
    """Stat the nearest existing ancestor of `path` without blocking forever.

    The probe runs on a worker thread. Calling exists/stat on the caller
    thread defeats the timeout when a parent mount is unresponsive.
    """
    target_dir = os.path.dirname(os.path.abspath(path)) or os.sep

    def probe() -> bool:
        current = target_dir
        seen = set()
        while current and current not in seen and not os.path.exists(current):
            seen.add(current)
            parent = os.path.dirname(current)
            if not parent or parent == current:
                return True
            current = parent
        os.stat(current or os.curdir)
        return True

    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(probe)
    try:
        future.result(timeout=timeout_seconds)
        return True
    except Exception:
        return False
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _harden_db_permissions(db_path: Path) -> None:
    """Keep the database and its WAL sidecars owner-readable only."""
    if os.name != "posix":
        return
    for candidate in (db_path, Path(str(db_path) + "-wal"), Path(str(db_path) + "-shm")):
        if candidate.exists():
            try:
                os.chmod(candidate, 0o600)
            except OSError:
                pass

def init_db(target_path_str: Optional[str] = None, force: bool = False):
    if target_path_str is None:
        target_path_str = str(Path(os.environ.get("ENGRAM_DB_PATH", DB_PATH)).resolve())
        
    if not force and target_path_str in _INITIALIZED_PATHS:
        return
        
    target_path = Path(target_path_str)
    
    if not check_storage_liveness(target_path_str):
        raise IOError(f"Storage path {target_path.parent} is unresponsive.")

    old_umask = None
    has_umask = hasattr(os, "umask")
    if has_umask:
        old_umask = os.umask(0o077)

    try:
        parent_existed = target_path.parent.exists()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            try:
                # Only tighten a directory this process just created, plus the
                # default data directory. Never chmod an arbitrary parent such
                # as /tmp when ENGRAM_DB_PATH points at a file inside it.
                if not parent_existed:
                    os.chmod(target_path.parent, 0o700)
                default_dir = Path(DB_PATH).expanduser()
                if target_path.parent.resolve() == default_dir.resolve():
                    os.chmod(target_path.parent, 0o700)
            except OSError:
                pass

        conn = sqlite3.connect(target_path_str, timeout=30.0)
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA busy_timeout = 30000;")
            
            conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT
            );
            """)
            
            conn.execute("""
            CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY,
                type TEXT DEFAULT 'memory',
                content TEXT,
                metadata TEXT,
                embedding BLOB,
                access_count INTEGER DEFAULT 0,
                last_accessed_at TEXT DEFAULT '',
                importance INTEGER DEFAULT 5,
                category TEXT DEFAULT 'general',
                project TEXT DEFAULT 'default',
                agent TEXT DEFAULT 'system',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """)
            
            conn.execute("""
            CREATE TABLE IF NOT EXISTS edges (
                source TEXT,
                target TEXT,
                relation TEXT,
                weight REAL DEFAULT 1.0,
                project TEXT DEFAULT 'default',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                valid_from TEXT DEFAULT '',
                valid_until TEXT DEFAULT '',
                superseded_by TEXT DEFAULT '',
                transaction_time TEXT DEFAULT '',
                PRIMARY KEY (source, target, relation)
            );
            """)
            
            conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(id, content, tokenize='trigram');")
            conn.execute("CREATE TRIGGER IF NOT EXISTS nodes_ai AFTER INSERT ON nodes BEGIN INSERT INTO nodes_fts(id, content) VALUES (new.id, new.content); END;")
            conn.execute("CREATE TRIGGER IF NOT EXISTS nodes_au AFTER UPDATE ON nodes BEGIN DELETE FROM nodes_fts WHERE id=old.id; INSERT INTO nodes_fts(id, content) VALUES (new.id, new.content); END;")
            conn.execute("CREATE TRIGGER IF NOT EXISTS nodes_ad AFTER DELETE ON nodes BEGIN DELETE FROM nodes_fts WHERE id=old.id; END;")
            
            has_vec = False
            try:
                import sqlite_vec
                conn.enable_load_extension(True)
                sqlite_vec.load(conn)
                conn.enable_load_extension(False)
                has_vec = True
            except Exception:
                pass

            if has_vec:
                try:
                    embedding_dim = int(os.environ.get("ENGRAM_EMBEDDING_DIM", "384"))
                    conn.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS nodes_vec USING vec0(id text primary key, embedding float[{embedding_dim}]);")
                    conn.execute("CREATE TRIGGER IF NOT EXISTS nodes_vec_ai AFTER INSERT ON nodes WHEN new.embedding IS NOT NULL BEGIN INSERT OR REPLACE INTO nodes_vec(id, embedding) VALUES (new.id, new.embedding); END;")
                    conn.execute("CREATE TRIGGER IF NOT EXISTS nodes_vec_au AFTER UPDATE ON nodes WHEN new.embedding IS NOT NULL BEGIN DELETE FROM nodes_vec WHERE id = old.id; INSERT OR REPLACE INTO nodes_vec(id, embedding) VALUES (new.id, new.embedding); END;")
                    conn.execute("CREATE TRIGGER IF NOT EXISTS nodes_vec_ad AFTER DELETE ON nodes BEGIN DELETE FROM nodes_vec WHERE id = old.id; END;")
                except Exception:
                    pass

            conn.execute("INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (1, datetime('now'));")
            conn.commit()
            _INITIALIZED_PATHS.add(target_path_str)
        except sqlite3.Error as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
        _harden_db_permissions(target_path)
    finally:
        if has_umask and old_umask is not None:
            os.umask(old_umask)

_THREAD_LOCAL = threading.local()

class PooledConnection:
    __slots__ = ("_raw_conn", "_path_str")
    def __init__(self, raw_conn, path_str: str):
        object.__setattr__(self, "_raw_conn", raw_conn)
        object.__setattr__(self, "_path_str", path_str)
    def close(self):
        try:
            if getattr(self._raw_conn, "in_transaction", False):
                self._raw_conn.rollback()
        except Exception:
            pass
    def close_raw(self):
        try:
            self._raw_conn.close()
        except Exception:
            pass
    def __enter__(self):
        return self._raw_conn.__enter__()
    def __exit__(self, exc_type, exc_val, exc_tb):
        return self._raw_conn.__exit__(exc_type, exc_val, exc_tb)
    def __getattr__(self, name):
        return getattr(self._raw_conn, name)
    def __setattr__(self, name, value):
        if name in self.__slots__:
            object.__setattr__(self, name, value)
        else:
            setattr(self._raw_conn, name, value)

def _configure_connection(conn):
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 30000;")
    conn.execute("PRAGMA cache_size = -64000;")
    conn.execute("PRAGMA mmap_size = 268435456;")
    
    def safe_power(base, exp):
        try: return math.pow(max(0.001, float(base)), float(exp))
        except Exception: return 0.0
    conn.create_function("POWER", 2, safe_power)
    try:
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except Exception:
        pass

def get_db(force_new: bool = False):
    target_path = Path(os.environ.get("ENGRAM_DB_PATH", DB_PATH)).resolve()
    target_path_str = str(target_path)
    if target_path_str not in _INITIALIZED_PATHS or not target_path.exists():
        init_db(target_path_str)

    if force_new:
        conn = sqlite3.connect(target_path_str, timeout=30.0)
        _configure_connection(conn)
        _harden_db_permissions(target_path)
        return conn

    if not hasattr(_THREAD_LOCAL, "conns"):
        _THREAD_LOCAL.conns = {}

    raw_conn = _THREAD_LOCAL.conns.get(target_path_str)
    if raw_conn is None:
        raw_conn = sqlite3.connect(target_path_str, timeout=30.0)
        _configure_connection(raw_conn)
        _harden_db_permissions(target_path)
        _THREAD_LOCAL.conns[target_path_str] = raw_conn

    return PooledConnection(raw_conn, target_path_str)

def close_thread_connections():
    """Close sqlite connections cached on this thread.

    The cache stores raw connections. Calling the pool wrapper's close_raw()
    left those connections open and leaked file descriptors.
    """
    if hasattr(_THREAD_LOCAL, "conns"):
        for conn in list(_THREAD_LOCAL.conns.values()):
            try:
                conn.close()
            except Exception:
                pass
        _THREAD_LOCAL.conns.clear()

def optimize_and_checkpoint(conn=None) -> Dict[str, Any]:
    close_when_done = False
    if conn is None:
        conn = get_db()
        close_when_done = True
    try:
        wal_res = conn.execute("PRAGMA wal_checkpoint(TRUNCATE);").fetchall()
        conn.execute("PRAGMA optimize;")
        return {"status": "optimized", "checkpoint": wal_res}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        if close_when_done:
            conn.close()
