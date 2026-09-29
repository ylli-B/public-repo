"""evmax — shared platform for expected-value maximising systems.

Domain code (MLB DFS, NFL ATS, and whatever comes next) lives outside this
package and depends on it, never the other way round. If something here imports
a sport, it is in the wrong place.

What belongs here:
  notify    delivery of alerts to a human, whatever the domain
  runlog    capturing output from unattended scheduled runs
  staking   turning an edge and a bankroll into a stake

What does not: feature engineering, market-specific logic, model selection.
"""

from __future__ import annotations

__all__ = ["notify", "runlog", "staking"]
