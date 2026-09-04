import unittest, os
from engine import Quote,PaperAccount,scalp_score
class T(unittest.TestCase):
    def test_budget_reuse(self):
        os.environ["PAPER_INITIAL_CASH"]="1000000";os.environ["PAPER_DAILY_BUDGET"]="200000"
        a=PaperAccount();q=Quote("000001","테스트")
        q.mark(100000);self.assertIsNotNone(a.buy(q,2))
        q.mark(110000);a.mark(q.code,q.price);self.assertIsNotNone(a.sell(q.code,q.price))
        self.assertEqual(a.held_cost(),0)
    def test_score_bounds(self):
        q=Quote("000001")
        for i in range(50):q.mark(1000+i*3,10000)
        s,_=scalp_score(q,10);self.assertTrue(0<=s<=100)
if __name__=="__main__":unittest.main()
