import asyncio
import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
from alert_store import AlertStore
import signal_alerter as service


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = AlertStore(':memory:')
        self.signal = dict(pair='BTCUSDT', direction='BUY', entry=100, sl=90, tp=120, confluence='8', mode='LIVE')
        self.store.add(-1, 1, self.signal)
        self.row = self.store.pending(900)[0]

    def tearDown(self):
        self.store.db.close()

    async def test_failed_push_is_scheduled_for_retry(self):
        with patch.object(service, 'fire_alarm', AsyncMock(side_effect=RuntimeError('offline'))):
            await service.deliver_push(self.store, self.row, self.signal)
        row = self.store.pending(900)[0]
        self.assertEqual(row['push_count'], 0)
        self.assertGreater(row['next_push'], 0)

    async def test_acknowledgement_and_push_limit_stop_pushes(self):
        for changes in ({'acknowledged': 1}, {'acknowledged': 0, 'push_count': service.MAX_PUSHES}):
            self.store.update(self.row['id'], **changes)
            with patch.object(service, 'fire_alarm', AsyncMock()) as alarm:
                await service.deliver_push(self.store, self.store.pending(900)[0], self.signal)
                alarm.assert_not_awaited()

    async def test_render_failure_still_delivers_acknowledgeable_text(self):
        bot = SimpleNamespace(send_message=AsyncMock())
        with patch.object(service, 'generate_signal_chart', side_effect=RuntimeError('render error')):
            await service.deliver_card(SimpleNamespace(bot=bot), self.store, self.row, self.signal)
        bot.send_message.assert_awaited_once()
        self.assertIsNotNone(bot.send_message.call_args.kwargs['reply_markup'])
        self.assertEqual(self.store.pending(900)[0]['card_sent'], 1)

    async def test_success_counts_push(self):
        with patch.object(service, 'fire_alarm', AsyncMock()):
            await service.deliver_push(self.store, self.row, self.signal)
        self.assertEqual(self.store.pending(900)[0]['push_count'], 1)
