# Star Trader archaeology

The recovered source is Dave Kaufman's 1974 Star Trader BASIC listing,
published in the People's Computer Company newsletter and preserved in the
`philspil66/StarTrader` source repository.  The HP BASIC setup and main modules
were inspected directly.

Mechanisms retained in Redos:

- star systems are places with a development level and routes between them;
- six goods have fixed reference prices;
- local net production/need comes from the recovered three-class `M` and `C`
  matrices;
- stocks are updated over time and prices move down with surplus and up with
  shortage;
- ships/actors travel a route for elapsed time, then trade locally;
- the BASIC game bounds bargaining to a small number of rounds, which becomes
  an explicit `bargain` helper;
- money is held by the actor or business and goods are canonical inventory
  lots, so buying/selling changes both physical inventory and wealth.

Bank accounts and ship cargo limits are deliberately deferred.  The first
compatible slice needs places, differentiated markets, physical goods,
transactions, and travel; it does not need Star Trader's tape save format or
interactive BASIC shell.
