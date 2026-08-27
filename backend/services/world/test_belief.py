# Velluma - belief 域测试（B3 · docs/world-kernel-foundation.md §4 不变量 7）
# AGPL-3.0
"""四值可答 + 曝光推导 + 误信优先级 + fold belief 域接线 + guard 命题化。"""
import asyncio
import tempfile
import unittest
import uuid
from pathlib import Path

import backend.models as m
from backend.db_sqlite.engine import build_sqlite_engine, build_sqlite_sessionmaker
from backend.db_sqlite.schema import init_db_sqlite
from backend.services.world.belief import (
    BELIEVES_FALSE, KNOWS, UNKNOWN, fold_belief, proposition_status,
)

BOOK = uuid.UUID("b3000000-0000-4000-8000-0000000000b1")
ALICE = "b3000000-0000-4000-8000-0000000000e1"
BOB = "b3000000-0000-4000-8000-0000000000e2"
PROP = "b3000000-0000-4000-8000-0000000000a1"
EVT = "b3000000-0000-4000-8000-0000000000f1"


def _ev(etype, ts, payload, participants=None):
    return {
        "id": f"{etype}-{ts}",
        "event_type": etype,
        "time_start": ts,
        "payload": payload,
        "participant_ids": participants or [],
    }


class TestBeliefFold(unittest.TestCase):
    def test_told_and_discover_and_participant_exposure(self):
        events = [
            _ev("told", 1, {"subject": ALICE, "proposition_ref": PROP}),
            _ev("discover", 2, {"subject": BOB, "evidence_of": EVT}, participants=[ALICE]),
        ]
        state = fold_belief(events, t=10)
        self.assertIn(PROP, state[ALICE]["knows_propositions"])
        self.assertIn(EVT, state[BOB]["knows_events"])
        self.assertIn(EVT, state[ALICE]["knows_events"])  # 参与者在场曝光

    def test_time_filter(self):
        events = [_ev("told", 50, {"subject": ALICE, "proposition_ref": PROP})]
        state = fold_belief(events, t=10)
        self.assertEqual(state, {})

    def test_misbelieve_overrides_knows(self):
        events = [
            _ev("told", 1, {"subject": ALICE, "proposition_ref": PROP}),
            _ev("misbelieve", 5, {
                "subject": BOB, "proposition_ref": PROP,
                "false_content": "他以为守塔人是仇人",
            }),
        ]
        state = fold_belief(events, t=10)
        self.assertEqual(proposition_status(PROP, [BOB], state), BELIEVES_FALSE)
        self.assertEqual(proposition_status(PROP, [ALICE], state), KNOWS)

    def test_unknown_when_no_evidence_or_empty_perspective(self):
        state = fold_belief([], t=10)
        self.assertEqual(proposition_status(PROP, [ALICE], state), UNKNOWN)
        self.assertEqual(proposition_status(PROP, [], state), UNKNOWN)


class TestFoldBeliefDomain(unittest.TestCase):
    def test_fold_domain_wired_with_db(self):
        with tempfile.TemporaryDirectory() as td:
            engine = build_sqlite_engine(Path(td) / "belief.db")
            maker = build_sqlite_sessionmaker(engine)
            asyncio.run(init_db_sqlite(engine, maker))
            try:
                async def run():
                    from backend.services.world.fold import fold
                    async with maker() as s:
                        s.add(m.Book(id=BOOK, title="认知测试书"))
                        s.add_all([
                            m.WorldEvent(
                                book_id=BOOK, sequence_num=1, event_type="told",
                                time_start=1, time_end=1,
                                payload={"subject": ALICE, "proposition_ref": PROP},
                            ),
                            m.WorldEvent(
                                book_id=BOOK, sequence_num=2, event_type="misbelieve",
                                time_start=2, time_end=2,
                                payload={
                                    "subject": BOB, "proposition_ref": PROP,
                                    "false_content": "误会",
                                },
                            ),
                        ])
                        await s.flush()
                        out = await fold(
                            s, str(BOOK), t=10, domains=("belief",),
                            perspective_set=[ALICE, BOB],
                        )
                        b = out["belief"]
                        self.assertEqual(b["proposition_status"].get(PROP), BELIEVES_FALSE)
                        self.assertIn(PROP, b["perspective"][ALICE]["knows_propositions"])
                        self.assertEqual(len(b["perspective"][BOB]["believes_false"]), 1)
                asyncio.run(run())
            finally:
                asyncio.run(engine.dispose())


class TestGuardProposition(unittest.TestCase):
    def test_canon_leak_carries_node_id(self):
        from backend.services.validation.ghost_guard import check_ghost_text
        warnings = check_ghost_text(
            "他终于说出了守塔人身份四个字。守塔人身份。",
            None,
            canon_private_labels=["守塔人身份"],
            canon_node_ids_by_label={"守塔人身份": PROP},
        )
        leaks = [w for w in warnings if w["kind"] == "canon_leak"]
        self.assertTrue(leaks)
        self.assertEqual(leaks[0].get("canon_node_id"), PROP)


if __name__ == "__main__":
    unittest.main()
