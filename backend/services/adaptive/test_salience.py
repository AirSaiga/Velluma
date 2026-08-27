# Velluma - 热层显著性测试（B7 · docs/world-cognition-architecture.md §4）
# AGPL-3.0
"""三族信号 × 段距衰减 × 六槽配额 × 防窄化的行为锁。"""
import unittest

from backend.services.adaptive.salience import compute_salience

CANVAS = "\n".join([
    "林尘拧紧了螺栓。",          # 段距 4（τ=3 → 弱）
    "车间里很安静。",            # 段距 3
    "林尘想起白露说过的话。",    # 段距 2
    "警报响了。",                # 段距 1
    "林尘抬头看向白露。",        # 段距 0
])


class TestSalience(unittest.TestCase):
    def test_recent_mention_dominates(self):
        hot = compute_salience(
            canvas_text=CANVAS,
            entity_names={"e1": ["林尘"], "e2": ["白露"]},
            priors={},
        )
        top3 = [e.title for e in hot if e.slot == "top"]
        self.assertEqual(top3[0], "林尘")   # 3 次提及 + 段距近

    def test_paragraph_distance_decay(self):
        near = compute_salience("远客。\n远客。", {"e1": ["远客"]})
        far = compute_salience("远客。\n甲。\n乙。\n丙。\n丁。\n戊。", {"e1": ["远客"]})
        self.assertGreater(
            next(e.score for e in near if e.title == "远客"),
            next(e.score for e in far if e.title == "远客"),
        )

    def test_neglected_important_slot(self):
        hot = compute_salience(
            canvas_text=CANVAS,
            entity_names={"e1": ["林尘"], "e9": ["守塔人"]},
            priors={"守塔人": 9},  # 高先验且 8 段未提
        )
        neglected = [e for e in hot if e.slot == "neglected"]
        self.assertEqual(len(neglected), 1)
        self.assertEqual(neglected[0].title, "守塔人")

    def test_present_silent_and_system_slots(self):
        hot = compute_salience(
            canvas_text="林尘拧螺栓。",
            entity_names={"e1": ["林尘"], "e2": ["沉默者"]},
            priors={},
            present_names=["沉默者"],
            open_loops=["灯塔里藏着什么（伏笔）"],
        )
        slots = {e.slot for e in hot}
        self.assertIn("present_silent", slots)
        self.assertIn("system", slots)

    def test_behavior_multiplier_and_six_slot_cap(self):
        hot = compute_salience(
            canvas_text="甲乙丙丁戊己庚辛壬癸都在场。",
            entity_names={f"e{i}": [c] for i, c in enumerate("甲乙丙丁戊己庚辛壬癸")},
            priors={},
            behavior_mult={"甲": 2.0, "乙": 0.1},
        )
        self.assertLessEqual(len(hot), 6)
        titles = [e.title for e in hot if e.slot == "top"]
        self.assertEqual(titles[0], "甲")   # 乘子放大
        self.assertNotIn("乙", titles[:3])  # 乘子压制


if __name__ == "__main__":
    unittest.main()
