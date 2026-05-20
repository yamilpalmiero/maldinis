from django.test import SimpleTestCase

from predictions.data.third_place_combinations import THIRD_PLACE_COMBINATIONS

VALID_GROUPS = set("ABCDEFGHIJKL")
EXPECTED_MATCH_KEYS = {"74", "77", "79", "80", "81", "82", "85", "87"}


class ThirdPlaceCombinationsDatasetTest(SimpleTestCase):

    def test_1_exactly_495_entries(self):
        self.assertEqual(len(THIRD_PLACE_COMBINATIONS), 495)

    def test_2_all_keys_are_frozensets_of_8_valid_groups(self):
        for key in THIRD_PLACE_COMBINATIONS:
            self.assertIsInstance(key, frozenset, msg=f"Key {key!r} is not a frozenset")
            self.assertEqual(len(key), 8, msg=f"Key {sorted(key)} does not have 8 groups")
            self.assertTrue(
                key <= VALID_GROUPS,
                msg=f"Key {sorted(key)} contains invalid groups: {key - VALID_GROUPS}",
            )

    def test_3_each_entry_assigns_every_qualifying_group_exactly_once(self):
        for key, assignment in THIRD_PLACE_COMBINATIONS.items():
            assigned_groups = set(assignment.values())
            self.assertEqual(
                assigned_groups,
                key,
                msg=(
                    f"For key {sorted(key)}: assigned groups {sorted(assigned_groups)} "
                    f"do not match qualifying groups"
                ),
            )

    def test_4_each_entry_has_exactly_the_8_required_match_keys(self):
        for key, assignment in THIRD_PLACE_COMBINATIONS.items():
            self.assertEqual(
                set(assignment.keys()),
                EXPECTED_MATCH_KEYS,
                msg=f"For key {sorted(key)}: match keys are {set(assignment.keys())}",
            )

    def test_5_spot_check_three_known_combinations(self):
        # ── Combination 1 (Wikipedia row 1): groups E F G H I J K L ──────────
        # Wikipedia: 1A=3E, 1B=3J, 1D=3I, 1E=3F, 1G=3H, 1I=3G, 1K=3L, 1L=3K
        # Mapping: 1A→M79, 1B→M85, 1D→M81, 1E→M74, 1G→M82, 1I→M77, 1K→M87, 1L→M80
        key1 = frozenset({"E", "F", "G", "H", "I", "J", "K", "L"})
        expected1 = {"74": "F", "77": "G", "79": "E", "80": "K", "81": "I", "82": "H", "85": "J", "87": "L"}
        self.assertIn(key1, THIRD_PLACE_COMBINATIONS)
        self.assertEqual(THIRD_PLACE_COMBINATIONS[key1], expected1)

        # ── Combination 9 (Wikipedia row 9): groups D E F G H I J K ──────────
        # Wikipedia: 1A=3E, 1B=3G, 1D=3J, 1E=3D, 1G=3H, 1I=3F, 1K=3I, 1L=3K
        key9 = frozenset({"D", "E", "F", "G", "H", "I", "J", "K"})
        expected9 = {"74": "D", "77": "F", "79": "E", "80": "K", "81": "J", "82": "H", "85": "G", "87": "I"}
        self.assertIn(key9, THIRD_PLACE_COMBINATIONS)
        self.assertEqual(THIRD_PLACE_COMBINATIONS[key9], expected9)

        # ── Combination 250 (Wikipedia row 250): groups A C D F G H I J ──────
        # Wikipedia: 1A=3H, 1B=3G, 1D=3J, 1E=3C, 1G=3A, 1I=3F, 1K=3D, 1L=3I
        key250 = frozenset({"A", "C", "D", "F", "G", "H", "I", "J"})
        expected250 = {"74": "C", "77": "F", "79": "H", "80": "I", "81": "J", "82": "A", "85": "G", "87": "D"}
        self.assertIn(key250, THIRD_PLACE_COMBINATIONS)
        self.assertEqual(THIRD_PLACE_COMBINATIONS[key250], expected250)
