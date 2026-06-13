# Final Forecast Prompt Contract

Synthesize the base model, deterministic agents, optional model-provider opinions, and Skeptic warnings.

Rules:

- Keep the base probability model as the anchor.
- Separate the 90-minute result from qualification.
- Treat simulated events only as conditional branches.
- Reduce confidence for missing or conflicting evidence.
- Never exceed 0.75 confidence before the result is known.
- Produce a technical entertainment forecast, never advice or certainty.
