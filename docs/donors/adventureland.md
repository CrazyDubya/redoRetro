# Adventureland archaeology

The implementation target was the Scott Adams Adventureland family of data
files, not a parser port.  The best available technical references were the
Apple II disassembly and the Scott Adams Adventure Compiler manual; the IF
Archive also records Morten Lohre's Adventureland C/BASIC source collection.

The useful invariant is a generic interpreter over declarative content:

- the database defines verbs/nouns, rooms, items, and actions;
- rooms carry descriptions and exits;
- every item has a location, with room `0` meaning nowhere and `-1` meaning
  carried;
- an action has a command pattern, conditions, and operations;
- all conditions must pass; the first successful command action runs;
- turn-independent occurrences are evaluated separately and all successful
  occurrences may run.

The original format also has flags and counters.  Redos does not inherit its
fixed opcode tables or two-word parser.  `redos.rules.RuleBook` preserves the
portable part: data describes predicates and actions, and the engine owns the
matching/execution loop.  The canonical `World` owns the resulting location,
ownership, and event state.

Uncertainty: the surviving format documentation disagrees on a few legacy
counter details and room-slot behaviors.  Those are not needed for the first
Redos rule layer, so they are intentionally not modeled.
