"""Service container shared by engines, ingestion and metrics."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from intel.db.connection import Database
from intel.providers.base import ProviderStatusRegistry
from intel.providers.blockscout import BlockscoutClient
from intel.providers.dexscreener import DexScreenerClient
from intel.providers.rpc import RpcClient
from intel.settings import IntelConfig, Settings

log = logging.getLogger(__name__)


@dataclass
class IntelContext:
    settings: Settings
    config: IntelConfig
    db: Database
    status: ProviderStatusRegistry
    rpc: RpcClient
    blockscout: BlockscoutClient
    dex: DexScreenerClient

    @classmethod
    def build(cls, settings: Settings | None = None, config: IntelConfig | None = None, db: Database | None = None) -> "IntelContext":
        settings = settings or Settings.load()
        config = config or IntelConfig.load(settings.config_path)
        db = db or Database(settings.db_path, backup_dir=settings.backup_dir)
        if db.health.get("status") in ("restored", "recreated"):
            log.error("database health at startup: %s", db.health)
        status = ProviderStatusRegistry(db)
        return cls(
            settings=settings,
            config=config,
            db=db,
            status=status,
            rpc=RpcClient(settings, status, db),
            blockscout=BlockscoutClient(settings, status, db),
            dex=DexScreenerClient(settings, status, db),
        )

    async def close(self) -> None:
        for c in (self.rpc, self.blockscout, self.dex):
            try:
                await c.close()
            except Exception:
                pass

    @property
    def chain_id(self) -> int:
        return self.settings.chain_id

    # ---- address classification ------------------------------------------ #
    def system_label(self, address: str | None) -> str | None:
        if not address:
            return None
        return self.config.data["system_addresses"].get(address.lower())

    def system_kind(self, address: str | None) -> str | None:
        label = self.system_label(address)
        return label.split(":", 1)[0] if label else None

    def is_system(self, address: str | None) -> bool:
        return self.system_label(address) is not None

    def add_system_address(self, address: str, label: str) -> None:
        self.config.data["system_addresses"][address.lower()] = label

    @property
    def pool_manager(self) -> str:
        return str(self.config.get("contracts.pool_manager")).lower()

    @property
    def airlock(self) -> str:
        return str(self.config.get("contracts.airlock")).lower()

    def quote_asset(self, address: str | None) -> dict | None:
        if not address:
            return None
        return self.config.data["quote_assets"].get(address.lower())
