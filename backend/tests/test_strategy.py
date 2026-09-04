import unittest
from backend.models import QuoteState
from backend.strategy import scalp_score, smart_score

class StrategyTest(unittest.TestCase):
    def make(self):
        q=QuoteState("005930","삼성전자")
        q.open=70000; q.prev_volume=100000
        for i in range(60):
            q.mark(70000+i*100, 180000)
        q.per=10; q.pbr=1.1; q.foreign_net=1; q.institution_net=1
        return q

    def test_scalp_is_bounded(self):
        s,_=scalp_score(self.make(),10,3)
        self.assertGreaterEqual(s,0); self.assertLessEqual(s,100)

    def test_smart_values_fundamentals(self):
        s,why=smart_score(self.make(),18,2)
        self.assertGreater(s,20)
        self.assertTrue(any("PER" in x for x in why))

if __name__=="__main__": unittest.main()
