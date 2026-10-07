"""Small driver interface: session mechanics never depend on a feature's fields."""
from typing import Protocol, Any


class Feature(Protocol):
    program: str
    key_column: str | None
    done: bool
    result: dict[str, Any] | None

    def advance(self, channel) -> None: ...


class DeferredFeature(Feature, Protocol):
    """Optional lifecycle: ERP work ends before bounded result materialization."""
    erp_done: bool

    def finish(self) -> None: ...
