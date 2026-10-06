# Stimulating Simulations kernels

This pass treats the collection as a source of small mechanisms rather than a
single architecture.  The shared implementations are:

- production consumes canonical input lots and creates output lots whose
  provenance includes the production event and consumed lots;
- witnessed incidents create per-person observations; recollection can diverge
  from the original content;
- statements update a listener's belief and trust without rewriting world truth
  or the speaker's observation;
- environmental propagation checks neighbor-local fuel and moisture;
- auctions settle money and canonical ownership through the same transaction
  gateway as markets;
- autonomous actor schedules create intentions and begin route travel, while
  aggregate populations advance with cheaper food/labor state.

The aggregate layer is deliberately additive: resolved actors remain ordinary
actors in `World`, and `reconcile_population` makes the resolution boundary
observable instead of maintaining a second detailed population.
