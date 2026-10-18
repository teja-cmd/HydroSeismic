from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Protocol


class FabricNotConfigured(RuntimeError):
    pass


class FabricTransactionError(RuntimeError):
    pass


class FabricGatewayClient(Protocol):
    async def submit_event(
        self,
        *,
        channel: str,
        chaincode: str,
        event: dict[str, Any],
    ) -> dict[str, Any]: ...

    async def transaction_status(
        self,
        *,
        channel: str,
        transaction_id: str,
    ) -> dict[str, Any]: ...


class BlockchainAdapter(Protocol):
    async def submit_event(self, event: dict[str, Any]) -> TransactionReceipt: ...

    async def transaction_status(self, transaction_id: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class TransactionReceipt:
    transaction_id: str
    status: str
    channel: str
    chaincode: str


@dataclass(frozen=True)
class FabricAdapter:
    client: FabricGatewayClient
    channel: str
    chaincode: str

    async def submit_event(self, event: dict[str, Any]) -> TransactionReceipt:
        result = await self.client.submit_event(
            channel=self.channel,
            chaincode=self.chaincode,
            event=event,
        )
        transaction_id = result.get("transaction_id")
        status = result.get("status")
        if not isinstance(transaction_id, str) or not transaction_id.strip():
            raise FabricTransactionError("Fabric gateway returned no transaction ID")
        if status not in {"SUBMITTED", "COMMITTED"}:
            raise FabricTransactionError("Fabric gateway did not confirm transaction submission")
        return TransactionReceipt(
            transaction_id=transaction_id,
            status=status,
            channel=self.channel,
            chaincode=self.chaincode,
        )

    async def transaction_status(self, transaction_id: str) -> dict[str, Any]:
        if not transaction_id.strip():
            raise ValueError("A real Fabric transaction ID is required")
        return await self.client.transaction_status(
            channel=self.channel,
            transaction_id=transaction_id,
        )


def create_fabric_adapter(client: FabricGatewayClient | None = None) -> FabricAdapter:
    mode = os.getenv("HYDROSEISMIC_LEDGER_MODE", "LOCAL_JSON").strip().upper()
    if mode != "FABRIC":
        raise FabricNotConfigured("Ledger mode is LOCAL_JSON; Fabric submission is disabled")
    channel = os.getenv("HYDROSEISMIC_FABRIC_CHANNEL", "").strip()
    chaincode = os.getenv("HYDROSEISMIC_FABRIC_CHAINCODE", "").strip()
    if not channel or not chaincode or client is None:
        raise FabricNotConfigured(
            "Fabric channel, chaincode, and an authenticated Gateway client are required"
        )
    return FabricAdapter(client=client, channel=channel, chaincode=chaincode)