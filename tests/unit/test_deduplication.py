"""Unit tests for deduplication logic."""
import pytest
from agents.deduplicate_node import normalize_title, title_overlap_ratio


def test_normalize_title_removes_noise():
    tokens = normalize_title("한국 축구 국가대표 평가전 결과")
    assert "한국" in tokens
    assert "축구" in tokens


def test_title_overlap_ratio_identical():
    t = normalize_title("한국 축구 국가대표 평가전")
    assert title_overlap_ratio(t, t) == 1.0


def test_title_overlap_ratio_different():
    t1 = normalize_title("한국 축구 평가전 승리")
    t2 = normalize_title("K리그 이적 시장 마감")
    ratio = title_overlap_ratio(t1, t2)
    assert ratio < 0.3


def test_title_overlap_ratio_partial():
    t1 = normalize_title("손흥민 국가대표 복귀 선언")
    t2 = normalize_title("손흥민 국가대표 부상 복귀")
    ratio = title_overlap_ratio(t1, t2)
    assert ratio > 0.5


def test_title_overlap_empty_sets():
    assert title_overlap_ratio(set(), {"a", "b"}) == 0.0
    assert title_overlap_ratio({"a"}, set()) == 0.0
