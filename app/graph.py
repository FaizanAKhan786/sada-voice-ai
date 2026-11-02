"""Optional LangGraph workflow; the base demo runs without this dependency.

Install `requirements-graph.txt` and set USE_LANGGRAPH=1. The graph separates
classification, policy fulfilment, and human-handoff routing.
"""
from __future__ import annotations
from typing import Any, TypedDict
from app.engine import Session, classify_intent, route_message

class AgentState(TypedDict, total=False):
    text: str
    session: Session
    intent: str
    result: dict[str, Any]


def make_graph():
    from langgraph.graph import END, START, StateGraph
    graph = StateGraph(AgentState)

    def understand(state: AgentState) -> dict:
        return {"intent": classify_intent(state["text"], state["session"].awaiting_order)}

    def act(state: AgentState) -> dict:
        return {"result": route_message(state["text"], state["session"]).to_dict()}

    def next_step(state: AgentState) -> str:
        return "handoff" if state["intent"] == "handoff" else "fulfill"

    graph.add_node("understand", understand)
    graph.add_node("fulfill", act)
    graph.add_node("handoff", act)
    graph.add_edge(START, "understand")
    graph.add_conditional_edges("understand", next_step, {"handoff": "handoff", "fulfill": "fulfill"})
    graph.add_edge("fulfill", END)
    graph.add_edge("handoff", END)
    return graph.compile()
