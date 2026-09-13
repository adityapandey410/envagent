"""LangGraph graph definition: plan -> execute -> verify -> (loop | end).

execute_node raises a LangGraph interrupt() before running a
destructive step; the checkpointer persists state at that pause point so
the run can be resumed (even after the process exits) once the interrupt
is answered.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from envagent.agent.checkpointer import get_checkpointer
from envagent.agent.nodes import execute_node, plan_node, verify_node
from envagent.agent.state import AgentState


def _route_after_verify(state: AgentState) -> str:
    if state["status"] in ("done", "failed"):
        return END
    return "execute"


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("plan", plan_node)
    graph.add_node("execute", execute_node)
    graph.add_node("verify", verify_node)

    graph.add_edge(START, "plan")
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", "verify")
    graph.add_conditional_edges(
        "verify", _route_after_verify, {"execute": "execute", END: END}
    )

    return graph.compile(checkpointer=get_checkpointer())
