from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

from backend.blockchain.adapter import (
    FabricNotConfigured,
    FabricTransactionError,
    create_fabric_adapter,
)


class FakeGateway:
    def __init__(self, result):
        self.result = result

    async def submit_event(self, *, channel, chaincode, event):
        return self.result

    async def transaction_status(self, *, channel, transaction_id):
        return {"transaction_id": transaction_id, "status": "COMMITTED"}


class FabricAdapterTests(unittest.TestCase):
    def test_local_json_mode_fails_closed(self) -> None:
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(FabricNotConfigured):
            create_fabric_adapter(FakeGateway({"transaction_id": "unused", "status": "SUBMITTED"}))

    def test_fabric_mode_requires_channel_chaincode_and_client(self) -> None:
        with patch.dict(os.environ, {"HYDROSEISMIC_LEDGER_MODE": "FABRIC"}, clear=True):
            with self.assertRaises(FabricNotConfigured):
                create_fabric_adapter()

    def test_receipt_uses_gateway_transaction_id(self) -> None:
        settings = {
            "HYDROSEISMIC_LEDGER_MODE": "FABRIC",
            "HYDROSEISMIC_FABRIC_CHANNEL": "relief-channel",
            "HYDROSEISMIC_FABRIC_CHAINCODE": "hydroseismic-events",
        }
        with patch.dict(os.environ, settings, clear=True):
            adapter = create_fabric_adapter(FakeGateway({"transaction_id": "real-gateway-id", "status": "SUBMITTED"}))
            receipt = asyncio.run(adapter.submit_event({"event_hash": "abc"}))

        self.assertEqual(receipt.transaction_id, "real-gateway-id")
        self.assertEqual(receipt.status, "SUBMITTED")

    def test_missing_gateway_transaction_id_is_never_fabricated(self) -> None:
        settings = {
            "HYDROSEISMIC_LEDGER_MODE": "FABRIC",
            "HYDROSEISMIC_FABRIC_CHANNEL": "relief-channel",
            "HYDROSEISMIC_FABRIC_CHAINCODE": "hydroseismic-events",
        }
        with patch.dict(os.environ, settings, clear=True):
            adapter = create_fabric_adapter(FakeGateway({"status": "SUBMITTED"}))
            with self.assertRaises(FabricTransactionError):
                asyncio.run(adapter.submit_event({"event_hash": "abc"}))


if __name__ == "__main__":
    unittest.main()