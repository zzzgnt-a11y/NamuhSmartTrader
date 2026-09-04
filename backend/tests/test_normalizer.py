import unittest
from backend.nh_runtime import pick, pick_code, PRICE_KEYS

class NormalizerTest(unittest.TestCase):
    def test_official_current_price_key(self):
        p={"Output_0":{"stck_prpr":"72300","iem_cd":"005930"}}
        self.assertEqual(pick(p,PRICE_KEYS),72300)
        self.assertEqual(pick_code(p),"005930")
if __name__=="__main__": unittest.main()
