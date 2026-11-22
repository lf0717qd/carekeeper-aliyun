# -*- coding: utf-8 -*-
"""Dependency-free LangGraph-style state graph for the agent turn.

Nodes: observe -> safety -> understand -> clarify/act -> reflect.
The deterministic rule planner remains the source of truth; this graph records
the path and makes session state explicit without pulling in a runtime dependency.
"""
from __future__ import annotations
import agent as _agent


class AgentGraph:
    def run(self, text: str, state=None):
        result = _agent.plan(text, state)
        path = ["observe", "safety", "understand"]
        intent = result.get("intent")
        action = result.get("action")
        if intent == "emergency":
            path += ["emergency", "handoff"]
        elif action == "handoff":
            path += ["fallback", "handoff"]
        elif action == "clarify":
            path += ["clarify"]
        elif action in ("kb", "business", "summary"):
            path += ["act:" + str(action), "reflect"]
        else:
            path += ["respond", "reflect"]
        result["graph"] = {"engine": "local_state_graph", "path": path}
        return result


GRAPH = AgentGraph()
