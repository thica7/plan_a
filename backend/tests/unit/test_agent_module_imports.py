import importlib


def test_synthesis_agents_import_after_timestamp_updates() -> None:
    modules = [
        "packages.agents.comparator.logic",
        "packages.agents.reflector.logic",
        "packages.agents.writer.logic",
    ]

    for module in modules:
        assert importlib.import_module(module)
