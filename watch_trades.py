# -*- coding: utf-8 -*-
"""Root entry point for Live Watchlist & Post-Trade Learning Monitor."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from Trade_Option.watchlist_monitor import main

if __name__ == "__main__":
    main()
