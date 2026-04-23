"""Pytest fixtures for KFA media intelligence pipeline tests."""
import sqlite3
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock
from langchain_core.messages import AIMessage


@pytest.fixture(autouse=True)
def use_temp_db(tmp_path, monkeypatch):
    """Redirect database to a temp file for each test."""
    db_path = str(tmp_path / "test_kfa.db")
    monkeypatch.setattr("config.settings.settings.database_path", db_path)
    # Re-point get_db_path
    import database.connection as db_conn
    monkeypatch.setattr(db_conn, "get_db_path", lambda: Path(db_path))
    db_conn.init_db()
    yield db_path


@pytest.fixture
def mock_haiku(monkeypatch):
    """Mock claude-haiku responses via ChatOpenAI."""
    mock = MagicMock()
    mock.ainvoke = AsyncMock()
    monkeypatch.setattr("agents.llm_client.get_haiku", lambda: mock)
    return mock


@pytest.fixture
def mock_sonnet(monkeypatch):
    """Mock claude-sonnet responses via ChatOpenAI."""
    mock = MagicMock()
    mock.ainvoke = AsyncMock()
    monkeypatch.setattr("agents.llm_client.get_sonnet", lambda: mock)
    return mock


@pytest.fixture
def sample_run_uuid():
    return "test-run-uuid-1234"


@pytest.fixture
def sample_run_date():
    return "2026-03-07"


@pytest.fixture
def base_state(sample_run_uuid, sample_run_date):
    """Base PipelineState for testing."""
    return {
        "run_date": sample_run_date,
        "run_uuid": sample_run_uuid,
        "generated_keywords": [],
        "raw_article_ids": [],
        "deduplicated_article_ids": [],
        "novelty_map": {},
        "new_article_ids": [],
        "skipped_continuing_count": 0,
        "analyzed_article_ids": [],
        "synthesis_id": None,
        "report_paths": {},
        "emails_sent": [],
        "errors": [],
        "stage": "init",
    }


def make_ai_response(content: str) -> AIMessage:
    return AIMessage(content=content)
