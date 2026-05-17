"""Base connector interface.

All publishing connectors must subclass BaseConnector and implement publish().
"""

import logging
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger(__name__)


class BaseConnector(ABC):
    """Abstract base class for publishing connectors."""

    name: str = "base"

    @abstractmethod
    def publish(self, folder: str, product: dict) -> bool:
        """
        Publish a product to the target platform.

        Args:
            folder: Product folder name (e.g. "20260517_200")
            product: Full product metadata dict from state_manager

        Returns:
            True on success, False on failure.
        """

    def _is_enabled(self) -> bool:
        return True

    def safe_publish(self, folder: str, product: dict) -> bool:
        """Publish with error handling and logging."""
        if not self._is_enabled():
            logger.info("%s connector is disabled — skipping %s", self.name, folder)
            return False
        try:
            logger.info("Publishing %s to %s...", folder, self.name)
            result = self.publish(folder, product)
            if result:
                logger.info("Published %s to %s successfully", folder, self.name)
            else:
                logger.warning("Publishing %s to %s returned False", folder, self.name)
            return result
        except Exception as exc:
            logger.error("Failed to publish %s to %s: %s", folder, self.name, exc)
            return False
