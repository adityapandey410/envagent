"""LangGraph graph: plan -> execute -> verify -> (loop | judge | end)."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from envagent.agent.checkpointer import get_checkpointer
from envagent.agent.nodes import execute_node, judge_node, plan_node, verify_node
from envagent.agent.state import AgentState


def _route_after_verify(state: AgentState) -> str:
    if state["status"] == "done":
        return "judge"
    if state["status"] == "failed":
        return END
    return "execute"


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("plan", plan_node)
    graph.add_node("execute", execute_node)
    graph.add_node("verify", verify_node)
    graph.add_node("judge", judge_node)

    graph.add_edge(START, "plan")
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", "verify")
    graph.add_conditional_edges(
        "verify", _route_after_verify, {"execute": "execute", "judge": "judge", END: END}
    )
    graph.add_edge("judge", END)

    return graph.compile(checkpointer=get_checkpointer())
