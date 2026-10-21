from collections.abc import Callable, Mapping

from langgraph.graph import END, START, StateGraph

from . import routing
from .nodes import stubs
from .nodes.approval import approval
from ..models.state import AXState

DEFAULT_NODES: dict[str, Callable] = {
    "collect": stubs.collect,
    "retrieve": stubs.retrieve,
    "assess": stubs.assess,
    "discover": stubs.discover,
    "evaluate": stubs.evaluate,
    "roadmap": stubs.roadmap,
    "approval": approval,
    "register": stubs.register,
}


def build_graph(checkpointer=None, nodes: Mapping[str, Callable] | None = None):
    """StateGraph 1개, 역할별 Node 8개 (§10).

    nodes로 일부 Node를 교체할 수 있다 (실제 구현 / 테스트용).
    """
    impl = {**DEFAULT_NODES, **(nodes or {})}

    g = StateGraph(AXState)
    for name, fn in impl.items():
        g.add_node(name, fn)

    g.add_edge(START, "collect")
    g.add_conditional_edges("collect", routing.after_collect, ["retrieve", END])
    g.add_edge("retrieve", "assess")
    g.add_edge("assess", "discover")
    g.add_edge("discover", "evaluate")
    g.add_conditional_edges("evaluate", routing.after_evaluate, ["discover", "roadmap"])
    g.add_edge("roadmap", "approval")
    g.add_conditional_edges("approval", routing.after_approval, ["register", END])
    g.add_edge("register", END)

    return g.compile(checkpointer=checkpointer)
