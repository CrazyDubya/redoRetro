# Redos

Redos is a persistent living-world simulation.  Its first implementation target is a small canonical world whose rooms, objects, rules, people, goods, and markets are data, while one engine adjudicates state transitions and records why they happened.

The initial donor work is recorded in [docs/donors/adventureland.md](docs/donors/adventureland.md) and [docs/donors/star-trader.md](docs/donors/star-trader.md).

Run the tests with:

```sh
python -m unittest discover -s tests -v
```

The package has no runtime dependencies.
