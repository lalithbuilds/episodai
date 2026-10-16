"""Regression tests for defects found in the repository review."""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from engram.cli import cmd_import
from engram.core import close_thread_connections, get_db, init_db, sqlite3
from engram.http_bridge import start_http_gateway
from engram.ingest import ingest_single_obsidian_file
from engram.server import (
    _retention_multiplier,
    auto_context,
    extract_and_save_memory,
    list_memories,
    query_graph,
    save_graph_relation,
    save_memory,
)


def test_package_version_matches_release():
    import engram
    from importlib.metadata import version

    assert engram.__version__ == "2.1.0"
    assert version("episodai") == "2.1.0"


def test_local_extra_matches_documented_install():
    import tomllib

    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    extras = data["project"]["optional-dependencies"]
    assert "fastembed>=0.4.0" in extras["local"]
    assert extras["local"] == extras["all"]


def test_extract_hashtags_create_edges():
    res = extract_and_save_memory(
        "Deploy the gateway #security #release_tag",
        project="hash_proj",
    )
    assert "tagged_as" in res
    assert "security" in res
    conn = get_db()
    rows = conn.execute(
        "SELECT source, relation, project FROM edges WHERE project = ?",
        ("hash_proj",),
    ).fetchall()
    conn.close()
    assert ("security", "tagged_as", "hash_proj") in rows
    assert ("release_tag", "tagged_as", "hash_proj") in rows


def test_single_file_reingest_replaces_chunks(tmp_path):
    note = tmp_path / "Note_One.md"
    note.write_text("alpha content about quartz [[LinkA]] #tag_alpha\n", encoding="utf-8")
    first = ingest_single_obsidian_file(note, project="obs_re")
    assert first["nodes"] == 1

    note.write_text("beta content revised about quartz [[LinkB]] #tag_beta\n", encoding="utf-8")
    second = ingest_single_obsidian_file(note, project="obs_re")
    assert second["nodes"] == 1

    conn = get_db()
    rows = conn.execute(
        "SELECT content FROM nodes WHERE project = ? AND category = 'obsidian'",
        ("obs_re",),
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    assert "beta content" in rows[0][0]
    assert "alpha content" not in rows[0][0]


def test_close_thread_connections_closes_sqlite_handle():
    conn = get_db()
    raw = conn._raw_conn
    close_thread_connections()
    with pytest.raises(sqlite3.ProgrammingError):
        raw.execute("SELECT 1")
    reopened = get_db()
    assert reopened.execute("SELECT 1").fetchone()[0] == 1
    reopened.close()


def test_new_database_directory_is_private(tmp_path):
    if os.name != "posix":
        pytest.skip("POSIX permission bits")
    nested = tmp_path / "freshdir" / "mem.sqlite"
    assert not nested.parent.exists()
    init_db(str(nested), force=True)
    assert stat.S_IMODE(nested.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(nested.stat().st_mode) == 0o600


def test_query_graph_does_not_treat_substrings_as_cycles():
    save_graph_relation("Host", "runs", "HostOS", project="subbug")
    save_graph_relation("HostOS", "uses", "OS", project="subbug")
    res = query_graph("Host", depth=3, project="subbug")
    assert "uses" in res
    assert "-> [OS]" in res


def test_retention_matches_actr_power_law():
    assert _retention_multiplier(0) == pytest.approx(1.0)
    assert _retention_multiplier(10) == pytest.approx((1.0 + 0.1 * 10) ** -0.5)
    assert _retention_multiplier(30) == pytest.approx((1.0 + 0.1 * 30) ** -0.5)
    assert _retention_multiplier(0) > _retention_multiplier(10) > _retention_multiplier(30)


def test_auto_context_escapes_markup():
    save_memory("Tom & Jerry <admin>", category='a"b', importance=9, project="xmlp")
    xml = auto_context(limit=3, min_importance=1, project="xmlp")
    assert "<admin>" not in xml
    assert "Tom &amp; Jerry &lt;admin&gt;" in xml
    assert 'category="a&quot;b"' in xml


def test_list_memories_clamps_negative_limit():
    save_memory("first memory alpha", importance=9, project="lim")
    save_memory("second memory beta", importance=8, project="lim")
    listed = list_memories(limit=-1, project="lim")
    assert "first memory alpha" in listed
    assert "second memory beta" not in listed


def test_import_rewrites_edges_onto_new_node_ids(tmp_path):
    save_memory("portable fact", project="kept_proj", importance=6)
    extract_and_save_memory("Widget [[Socket]] holds state", project="kept_proj")
    export_path = tmp_path / "export.json"
    from engram.cli import cmd_export

    cmd_export(str(export_path), project="kept_proj")
    original = json.loads(export_path.read_text(encoding="utf-8"))
    old_ids = {node["id"] for node in original["nodes"]}

    fresh = tmp_path / "fresh.sqlite"
    os.environ["ENGRAM_DB_PATH"] = str(fresh)
    from engram.core import _INITIALIZED_PATHS

    _INITIALIZED_PATHS.clear()
    close_thread_connections()
    init_db(str(fresh), force=True)
    cmd_import(str(export_path))

    conn = get_db()
    projects = {row[0] for row in conn.execute("SELECT DISTINCT project FROM nodes").fetchall()}
    assert projects == {"kept_proj"}
    edges = conn.execute(
        "SELECT target, relation FROM edges WHERE relation = 'is_referenced_by'"
    ).fetchall()
    node_ids = {row[0] for row in conn.execute("SELECT id FROM nodes").fetchall()}
    conn.close()
    assert edges
    for target, _relation in edges:
        assert target in node_ids
        assert target not in old_ids


def test_cli_import_keeps_project_from_file(tmp_path):
    payload = {
        "nodes": [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "content": "kept fact from file",
                "category": "general",
                "importance": 5,
                "project": "from_file",
                "agent": "system",
            }
        ],
        "edges": [
            {
                "source": "from_file_node",
                "target": "11111111-1111-1111-1111-111111111111",
                "relation": "links",
                "weight": 1,
                "project": "from_file",
            }
        ],
    }
    src = tmp_path / "in.json"
    src.write_text(json.dumps(payload), encoding="utf-8")
    env = os.environ.copy()
    env["ENGRAM_DB_PATH"] = str(tmp_path / "cli.sqlite")
    proc = subprocess.run(
        [sys.executable, "-m", "engram.cli", "import", str(src)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    listed = subprocess.run(
        [sys.executable, "-m", "engram.cli", "list", "--project", "from_file"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "kept fact from file" in listed.stdout
    graph = subprocess.run(
        [sys.executable, "-m", "engram.cli", "query-graph", "from_file_node", "--project", "from_file"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "links" in graph.stdout
    assert "11111111-1111-1111-1111-111111111111" not in graph.stdout


def test_public_http_bind_requires_api_key(monkeypatch):
    monkeypatch.delenv("ENGRAM_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ENGRAM_API_KEY"):
        start_http_gateway("0.0.0.0", 1)


def test_doctor_does_not_recommend_a_different_package(tmp_path):
    env = os.environ.copy()
    env["ENGRAM_DB_PATH"] = str(tmp_path / "doctor.sqlite")
    proc = subprocess.run(
        [sys.executable, "-m", "engram.cli", "doctor"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "engram[local]" not in proc.stdout
    assert "Embedding Backend" in proc.stdout
