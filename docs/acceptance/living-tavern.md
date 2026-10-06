# Living tavern acceptance notes

`redos.audit.tavern_report` answers patron questions from movement events,
current intentions, actor relationships, observations, statements, trust, and
beliefs.  `information_graph` exposes the separate layers directly.  It does
not infer omniscient answers for actors who have no observation or statement.

`validate_world` checks the basic conservation boundary: no negative lots,
unknown holders, negative actor cash, or dead actors are silently accepted.
`causal_chain` follows the event IDs recorded by state transitions.
