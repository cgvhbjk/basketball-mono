"""Entry point so `python -m basketball_scraper ...` dispatches to cli.main."""
from .cli import main
import sys

if __name__ == "__main__":
    sys.exit(main())
