"""Compatibility exports; graph.builder is the teammate graph assembly interface."""
from .nodes.implemented import approval_payload, display_roadmap, task_result, build_nodes
from .builder import build_graph as assemble_graph


def build_graph(gateway=None, reasoner=None, checkpointer=None, settings=None, *, nodes=None):
    if settings is not None:
        return assemble_graph(checkpointer=checkpointer, nodes=build_nodes(gateway, reasoner, settings))
    if gateway is not None:
        if checkpointer is not None:
            raise TypeError('checkpointer was supplied twice')
        checkpointer = gateway
    return assemble_graph(checkpointer=checkpointer, nodes=nodes)
