"""MARKET MAKING GAME: a separate game of making markets against bots on several numeric questions at once.

Independent of the rates engine, the TRAIN catalogue and the Live Desk episodes: it imports nothing from them and shares nothing with them but the local server and the shell.

    rng          deterministic streams keyed by (seed, labels)
    probability  dice / coin / integer / deck experiments, exact distributions, the hidden tape, and the effects (shocks) that act on them
    world        the curated world-knowledge bank and the public belief about one fact
    levels       the three difficulty levels
    markets      one market's data and the accounting convention
    bots         the counterparty personalities and their decisions
    generator    builds a game (markets, schedule, hidden shock plan) from a seed
    game         the round loop, quoting, execution, settlement, views, replay
    debrief      attribution of P&L to decisions and luck, after the last market resolves
    store        one JSON file per game under <home>/mmgame
"""
