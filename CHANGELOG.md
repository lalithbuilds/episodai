# Changelog

All notable changes to Episodai will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v2.1.1] - 2026-09-08

### Fixed
- Corrected benchmark reproduce command (`engram-alpha-mcp.git` → `episodai.git`, was returning 404)
- Corrected LongMemEval latency in BENCHMARKS.md (`0.176s` → `11.71s` to match committed results JSON)
- Corrected CI test count claim (`58/58` → `59 tests`, actual count is 59)
- Corrected database path in README architecture diagram (`engram.sqlite` → `engram_v3.db`)
- Populated `[all]` optional dependency in pyproject.toml (was empty, README claimed it installed packages)
- Removed empty v4 stub files (`v4_amx.py`, `v4_search.py`, `v4_telemetry.py`) — 27-35 byte placeholders shipped to PyPI

## [v2.1.0] - 2026-09-03

### Added
- 4-Way Reciprocal Rank Fusion (RRF) hybrid retrieval engine
- Apple Silicon AMX vector acceleration via Accelerate.framework (1.2M+ vecs/sec)
- Multi-tier hardware engine: AMX → C-BLAS → NumPy → pure Python fallback
- Bi-temporal knowledge graph with valid_from/valid_until/superseded_by tracking
- Recursive CTE graph traversal with cycle prevention
- Native Obsidian vault sync with `[[wikilink]]` parser
- ACT-R power-law cognitive decay modeling
- HTTP/SSE OpenAPI gateway for cloud web agents
- Published on PyPI as `episodai` (pip install episodai / uvx episodai)
- Smithery and Glama registry integration
- 59 unit tests across 14 test files
- Multi-language README translations (Chinese, Japanese, Spanish, German)
- LongMemEval benchmark: 100% accuracy (10/10), Recall@5 = 1.0
- Model Council Gauntlet stress test: 1,540 ops, 0 deadlocks, integrity verified
