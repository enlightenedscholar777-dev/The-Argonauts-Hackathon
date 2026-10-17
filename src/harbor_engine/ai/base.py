from dataclasses import dataclass
from typing import Protocol


class ProviderError(Exception):
    def __init__(self, category, retry_after=30):
        self.category = category
        self.retry_after = max(1, min(float(retry_after), 3600))
        super().__init__(category)


@dataclass
class ProviderResult:
    content: str
    usage: int | None = None


class Provider(Protocol):
    async def complete(self, snapshot: dict) -> ProviderResult: ...
    async def close(self) -> None: ...
