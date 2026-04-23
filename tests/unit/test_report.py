"""Unit tests for report template rendering."""
import pytest
from pathlib import Path
from jinja2 import Environment, FileSystemLoader


@pytest.fixture
def jinja_env():
    template_dir = Path(__file__).parent.parent.parent / "reports" / "templates"
    return Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)


@pytest.fixture
def sample_context():
    return {
        "run_date": "2026-03-07",
        "synthesis": {
            "executive_summary_ko": "오늘 한국 축구 미디어 브리핑입니다.",
            "executive_summary_en": "Today's KFA media briefing.",
            "sentiment_today": 0.35,
            "sentiment_trend": "improving",
        },
        "new_articles": [
            {
                "title": "손흥민 국가대표 복귀 발표",
                "url": "https://example.com/1",
                "summary_ko": "손흥민이 국가대표팀에 복귀합니다.",
                "summary_en": "Son Heung-min returns to the national team.",
                "risk_flag": "opportunity",
                "kfa_relevance_score": 9,
                "novelty_status": "new",
            }
        ],
        "developing_articles": [],
        "continuing_articles": [
            {"title": "K리그 이적 시장 동향", "days_active": 3, "novelty_status": "continuing"}
        ],
        "resolved_articles": [],
        "new_count": 1, "developing_count": 0, "continuing_count": 1, "resolved_count": 0,
        "total_analyzed": 1, "skipped_continuing_count": 1,
        "has_crisis": False,
        "crisis_alerts": [],
        "trending_narratives": [
            {"rank": 1, "title_ko": "손흥민 복귀", "title_en": "Son Return",
             "description_ko": "국가대표 복귀", "description_en": "National team return",
             "article_count": 3}
        ],
        "recommended_actions": [
            {"priority": 1, "action_ko": "공식 성명 발표", "action_en": "Issue official statement",
             "rationale_ko": "긍정적 여론 조성 필요"}
        ],
        "executive_summary_ko": "오늘 한국 축구 미디어 브리핑입니다.",
        "executive_summary_en": "Today's KFA media briefing.",
        "sentiment_today": 0.35,
        "sentiment_trend": "improving",
    }


def test_email_template_renders(jinja_env, sample_context):
    template = jinja_env.get_template("email_report.html.jinja2")
    html = template.render(**sample_context)
    assert "2026-03-07" in html
    assert "손흥민" in html
    assert "KFA" in html or "대한축구협회" in html


def test_email_template_shows_new_section(jinja_env, sample_context):
    template = jinja_env.get_template("email_report.html.jinja2")
    html = template.render(**sample_context)
    assert "신규" in html or "NEW" in html
    assert "손흥민 국가대표 복귀 발표" in html


def test_email_template_shows_continuing_section(jinja_env, sample_context):
    template = jinja_env.get_template("email_report.html.jinja2")
    html = template.render(**sample_context)
    assert "경과" in html or "CONTINUING" in html
    assert "K리그" in html


def test_email_template_no_crisis_banner_when_no_crisis(jinja_env, sample_context):
    template = jinja_env.get_template("email_report.html.jinja2")
    html = template.render(**sample_context)
    # No crisis alert should be shown
    assert "CC0000" not in html or "has_crisis" not in html or not sample_context["has_crisis"]
