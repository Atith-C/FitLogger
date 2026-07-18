import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class AnalyticsConfig(AppConfig):
    name = "analytics"

    def ready(self):
        """Warm pandas up at startup.

        The first DataFrame/groupby in a fresh process pays a large one-time
        initialisation cost (several seconds on pandas 3.x). Doing a throwaway
        operation here moves that cost to server boot, so a user's first visit
        to the Progress page is fast instead of stalling for seconds.
        """
        try:
            import pandas as pd

            pd.DataFrame({"a": [1, 1, 2], "b": [1.0, 2.0, 3.0]}).groupby(
                "a", as_index=False
            ).agg(total=("b", "sum"))
        except Exception:  # never let a warmup issue stop the app from starting
            logger.warning("pandas warmup skipped", exc_info=True)
