from __future__ import annotations

from collections import defaultdict, deque
from queue import Queue
from typing import DefaultDict

from app.ai.events import AgentEvent


class AgentEventStream:
    def __init__(self) -> None:
        self._history: DefaultDict[str, deque[AgentEvent]] = defaultdict(deque)

    def publish(self, event: AgentEvent) -> None:
        history = self._history[event.thread_id]
        history.append(event)
        while len(history) > 50:
            history.popleft()

    def subscribe(self, thread_id: str) -> Queue[AgentEvent]:
        queue: Queue[AgentEvent] = Queue()
        for event in self._history.get(thread_id, ()):
            queue.put(event)
        return queue
