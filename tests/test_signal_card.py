import unittest
from PIL import Image
from signal_card import situation, price, generate_signal_chart

class CardTests(unittest.TestCase):
    def test_situations(self):
        for side in ('BUY', 'SELL'):
            for order, vol, pose in [('LIMIT','Moderate','waiting'),('MARKET','Low','active'),('LIMIT','High','caution'),('MARKET','Extreme','caution'),('LIMIT','not high','waiting')]:
                self.assertEqual(situation(dict(direction=side, order_type=order, volatility=vol)), (side, pose))

    def test_price_precision(self):
        self.assertEqual(price(0.00000123), '0.00000123')
        self.assertEqual(price(65000.0), '65,000')

    def test_all_art_variants_render(self):
        for side in ('BUY', 'SELL'):
            for order, vol in [('LIMIT','Low'),('MARKET','Low'),('MARKET','High')]:
                sample = dict(pair='1000PEPEUSDT', direction=side, order_type=order, volatility=vol, entry=0.0000123, sl=0.00001, tp=0.00002, mode='SAMPLE', details=['A long note '*30]*6)
                with Image.open(generate_signal_chart(sample)) as image:
                    self.assertEqual(image.size, (1600,1040))
