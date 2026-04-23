"""LangGraph StateGraph definition — 8 nodes in sequence."""
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from models.state import PipelineState
from agents.keyword_node import run as keyword_run
from agents.collect_node import run as collect_run
from agents.filter_node import run as filter_run
from agents.deduplicate_node import run as deduplicate_run
from agents.novelty_node import run as novelty_run
from agents.analyze_node import run as analyze_run
from agents.synthesize_node import run as synthesize_run
from agents.report_node import run as report_run


def build_graph(checkpointer: AsyncSqliteSaver):
    """Build and compile the KFA media intelligence pipeline graph."""
    g = StateGraph(PipelineState)

    g.add_node("keywords",    keyword_run)
    g.add_node("collect",     collect_run)
    g.add_node("filter",      filter_run)
    g.add_node("deduplicate", deduplicate_run)
    g.add_node("novelty",     novelty_run)
    g.add_node("analyze",     analyze_run)
    g.add_node("synthesize",  synthesize_run)
    g.add_node("report",      report_run)

    g.set_entry_point("keywords")
    g.add_edge("keywords",    "collect")
    g.add_edge("collect",     "filter")
    g.add_edge("filter",      "deduplicate")
    g.add_edge("deduplicate", "novelty")
    g.add_edge("novelty",     "analyze")
    g.add_edge("analyze",     "synthesize")
    g.add_edge("synthesize",  "report")
    g.add_edge("report",      END)

    return g.compile(checkpointer=checkpointer)
