"""Evidence about a named client, and what it implies (level 5).

The trainee sees each named client's requests and the 10Y move over the step that followed. The ASSESSMENT turns the same observations
into P(informed | evidence) with the model that generates the flow, so judging a decision on "the information available at the time"
has a definite meaning. The trainee is never shown this number (that would do the inference for them); it is used to assess, and
revealed in the debrief.

Model (the generator's, stated as a training assumption): after a request from an informed client the level move over the next step is
Normal(mu + sign x drift, sd^2); after an uninformed one Normal(mu, sd^2). mu and sd carry the research view at its stated reliability
(treated as independent from step to step: an approximation, since the view is either right all session or not) and the step's vol.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Evidence:
    name: str
    sign: int               # +1 the client paid fixed (profits if rates rise), -1 it received
    move: float             # the level move (bp) over the step after its request
    sd: float               # sd of the move that is not the client's information
    drift: float            # the move an informed client's trade predicts (bp)
    mu: float = 0.0         # expected move from other known sources (the research view)


def posterior(prior: float, evidence: list[Evidence]) -> float:
    """P(informed | evidence) by Bayes: log-odds = logit(prior) + sum of log-likelihood ratios."""
    if not 0.0 < prior < 1.0:
        return prior
    lo = math.log(prior / (1.0 - prior))
    for e in evidence:
        m = e.move - e.mu
        lo += (e.sign * m * e.drift - 0.5 * e.drift ** 2) / e.sd ** 2
    lo = max(-50.0, min(50.0, lo))
    return 1.0 / (1.0 + math.exp(-lo))
