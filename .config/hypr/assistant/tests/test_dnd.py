"""The Dungeon Master mode: the record must hold whatever the model says.

    cd ~/hyprdots/.config/hypr/assistant && python3 -m unittest discover -s tests -v
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _sandbox  # noqa: E402,F401  (must come before hypr_agent)
import hypr_agent as a  # noqa: E402
import agent_modes  # noqa: E402
import dnd_mode as d  # noqa: E402

HERO = {"name": "Brin", "species": "Dwarf", "class": "Fighter", "background": "Soldier", "ac": 16,
        "abilities": {"str": 16, "dex": 12, "con": 14, "int": 8, "wis": 13, "cha": 10}, "skills": ["athletics", "perception"],
        "gold": {"gp": 10}, "equipment": [{"name": "Longsword", "damage": "1d8", "mastery": "Sap"}, {"name": "Rope", "qty": 2}]}
WIZARD = {**HERO, "name": "Elara", "class": "wizard", "spells": [{"name": "Fire Bolt", "level": 0}],
          "abilities": {"str": 8, "dex": 14, "con": 12, "int": 16, "wis": 12, "cha": 10}}


def call(tool, /, **kw):
    return d.TOOLS[tool](json.dumps(kw))


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=_sandbox.FAKE_HOME)
        self.addCleanup(shutil.rmtree, self.dir, True)
        for patch in (mock.patch.object(d, "DIR", [self.dir]), mock.patch.object(d, "GAME", [None]), mock.patch.object(d, "LISTENERS", [])):
            patch.start()
            self.addCleanup(patch.stop)
        saved = dict(agent_modes.STATE)
        self.addCleanup(agent_modes.STATE.update, saved)

    def hero(self, sheet=HERO):
        self.assertTrue(call("dnd_create_character", **sheet).startswith("Created"))
        return d.game()["character"]

    def dice(self, *values):
        """Fixes the next dice; each randint returns the next value."""
        patch = mock.patch.object(d.RNG, "randint", side_effect=list(values))
        patch.start()
        self.addCleanup(patch.stop)


class Character(Base):
    def test_derived_numbers_come_from_the_rules(self):
        c = self.hero()
        self.assertEqual((c["level"], c["max_hp"], c["hp"]), (1, 12, 12))        # d10 + Con +2
        self.assertEqual(c["saves"], ["str", "con"])
        self.assertEqual(d.proficiency(5), 3)
        self.assertEqual(d.modifier(9), -1)
        self.assertEqual(d.game()["character"]["slots"], {})

    def test_casters_get_slots_and_a_save_dc(self):
        c = self.hero(WIZARD)
        self.assertEqual(c["slots"], {"1": {"max": 2, "used": 0}})
        self.assertEqual(d.spell_save_dc(c), 13)

    def test_bad_sheets_are_refused(self):
        self.assertIn("Rejected", call("dnd_create_character", **{**HERO, "class": "Jedi"}))
        self.assertIn("Rejected", call("dnd_create_character", **{**HERO, "abilities": {"str": 40}}))
        self.assertIn("Rejected", call("dnd_create_character", **{**HERO, "skills": ["hacking"]}))
        self.assertIsNone(d.game()["character"])

    def test_one_character_per_campaign(self):
        self.hero()
        self.assertIn("already exists", call("dnd_create_character", **WIZARD))


class Dice(Base):
    def test_parsing(self):
        self.dice(3, 4, 2)
        self.assertEqual(d.roll_dice("2d6+1d4+3"), (12, [3, 4, 2], 3))

    def test_a_critical_doubles_dice_not_modifiers(self):
        self.dice(1, 2)
        self.assertEqual(d.roll_dice("1d8+3", crit=True), (6, [1, 2], 3))

    def test_nonsense_is_refused(self):
        for bad in ("fish", "1000d6", "2d6+rm"):
            with self.assertRaises(d.Rejected):
                d.roll_dice(bad)

    def test_advantage_cancels_out(self):
        self.assertEqual(d._advantage("advantage", "disadvantage"), "")
        self.assertEqual(d._advantage("adv", ""), "advantage")


class Checks(Base):
    def test_skill_uses_the_sheet(self):
        self.hero()
        self.dice(10)
        self.assertIn("rolled 10, +3 = 13 vs DC 13: SUCCESS", call("dnd_check", check="perception", dc=13))  # Wis +1, prof +2

    def test_save_proficiency(self):
        self.hero()
        self.dice(10)
        self.assertIn("+5 = 15", call("dnd_check", check="str save"))
        self.dice(10)
        self.assertIn("+1 = 11", call("dnd_check", check="dexterity saving throw"))

    def test_a_natural_20_is_not_automatic_on_checks(self):
        self.hero()
        self.dice(20)
        self.assertIn("FAILURE", call("dnd_check", check="persuasion", dc=25))

    def test_exhaustion_lowers_the_roll(self):
        self.hero()
        call("dnd_update", exhaustion=2)
        self.dice(10)
        self.assertIn("-1 = 9", call("dnd_check", check="perception"))

    def test_poison_forces_disadvantage(self):
        self.hero()
        call("dnd_update", add_conditions=["poisoned"])
        self.dice(18, 4)
        self.assertIn("kept 4", call("dnd_check", check="perception"))

    def test_unknown_skill(self):
        self.hero()
        self.assertIn("Rejected", call("dnd_check", check="vibes"))


class Sheet(Base):
    def test_you_cannot_spend_what_you_do_not_have(self):
        self.hero()
        self.assertIn("cannot afford", call("dnd_update", gp=-50))
        self.assertEqual(d.game()["character"]["gold"]["gp"], 10)

    def test_change_is_given(self):
        self.hero()
        call("dnd_update", sp=-5)
        self.assertEqual(d.game()["character"]["gold"], {"gp": 9, "sp": 5, "cp": 0})

    def test_you_cannot_lose_what_you_do_not_own(self):
        self.hero()
        self.assertIn("does not have", call("dnd_inventory", remove=["Vorpal Sword"]))
        self.assertIn("only has 2", call("dnd_inventory", remove=[{"name": "Rope", "qty": 5}]))

    def test_items_stack_and_leave(self):
        self.hero()
        call("dnd_inventory", add=[{"name": "rope", "qty": 1}])
        self.assertEqual(d._item(d.game()["character"], "rope")["qty"], 3)
        call("dnd_inventory", remove=[{"name": "Rope", "qty": 3}])
        self.assertIsNone(d._item(d.game()["character"], "rope", required=False))

    def test_a_refusal_changes_nothing(self):
        self.hero()
        call("dnd_update", gp=-1, hp=-5, slot_used=9)
        c = d.game()["character"]
        self.assertEqual((c["gold"]["gp"], c["hp"]), (10, 12))

    def test_temporary_hp_soak_first_and_do_not_stack(self):
        self.hero()
        call("dnd_update", temp_hp=5)
        call("dnd_update", temp_hp=3)
        call("dnd_update", hp=-7)
        c = d.game()["character"]
        self.assertEqual((c["temp_hp"], c["hp"]), (0, 10))

    def test_slots_run_out(self):
        self.hero(WIZARD)
        call("dnd_update", slot_used=1)
        call("dnd_update", slot_used=1)
        self.assertIn("no level 1 spell slots are left", call("dnd_update", slot_used=1))

    def test_level_up_needs_xp_or_a_milestone(self):
        self.hero()
        self.assertIn("does not have the XP", call("dnd_update", level_up=True))
        call("dnd_update", xp=300)
        self.assertIn("Level 2", call("dnd_update", level_up=True))
        self.assertEqual(d.game()["character"]["max_hp"], 12 + 8)

    def test_only_real_conditions(self):
        self.hero()
        self.assertIn("Rejected", call("dnd_update", add_conditions=["sleepy"]))


class Death(Base):
    def test_dropping_and_saving(self):
        c = self.hero()
        call("dnd_update", hp=-12)
        c = d.game()["character"]
        self.assertEqual(c["hp"], 0)
        self.assertIn("unconscious", c["conditions"])
        self.dice(1)
        self.assertIn("two failures", call("dnd_check", check="death"))
        self.dice(5)
        self.assertIn("DIES", call("dnd_check", check="death"))
        self.assertTrue(d.game()["character"]["dead"])
        self.assertIn("dead", call("dnd_update", gp=1))

    def test_massive_damage_kills(self):
        self.hero()
        call("dnd_update", hp=-24)
        self.assertTrue(d.game()["character"].get("dead"))

    def test_a_natural_20_gets_you_up(self):
        self.hero()
        call("dnd_update", hp=-12)
        self.dice(20)
        call("dnd_check", check="death")
        c = d.game()["character"]
        self.assertEqual(c["hp"], 1)
        self.assertNotIn("unconscious", c["conditions"])

    def test_three_successes_stabilise(self):
        self.hero()
        call("dnd_update", hp=-12)
        for _ in range(3):
            self.dice(12)
            result = call("dnd_check", check="death")
        self.assertIn("Stable", result)


class Combat(Base):
    def begin(self, goblin_first=False):
        self.hero()
        self.dice(*((15, 3) if goblin_first else (3, 15)))  # goblin's initiative, then Brin's
        return call("dnd_combat", action="start", enemies=[{"name": "Goblin", "hp": 7, "ac": 13, "init_bonus": 2}])

    def test_initiative_order(self):
        out = self.begin(goblin_first=True)
        self.assertIn("Goblin (17), Brin (4)", out)
        self.assertIn("Goblin's turn", out)

    def test_same_names_are_told_apart(self):
        self.hero()
        call("dnd_combat", action="start", enemies=[{"name": "Wolf", "hp": 5, "ac": 12}, {"name": "Wolf", "hp": 5, "ac": 12}])
        names = {e["name"] for e in d.game()["combat"]["order"]}
        self.assertLessEqual({"Wolf 1", "Wolf 2"}, names)

    def test_a_hit_uses_the_sheet_and_lands_on_the_enemy(self):
        self.begin()
        self.dice(10, 5)
        out = call("dnd_attack", weapon="Longsword", target="Goblin")
        self.assertIn("rolled 10, +5 = 15 vs AC 13: HIT for 8 damage", out)
        self.assertIn("DEFEATED", out)
        self.assertTrue(d.game()["combat"]["economy"]["action"])

    def test_a_natural_1_always_misses(self):
        self.begin()
        self.dice(1)
        self.assertIn("MISS", call("dnd_attack", weapon="Longsword", target="Goblin", ac=1))

    def test_a_natural_20_always_hits_and_doubles_dice(self):
        self.begin()
        d.game()["combat"]["order"][1]["hp"] = 99
        d.game()["combat"]["order"][1]["ac"] = 40
        self.dice(20, 2, 3)
        self.assertIn("CRITICAL HIT for 8 damage", call("dnd_attack", weapon="Longsword", target="Goblin"))

    def test_you_cannot_swing_what_you_do_not_own(self):
        self.begin()
        self.assertIn("does not have", call("dnd_attack", weapon="Excalibur", target="Goblin"))

    def test_you_cannot_cast_what_you_do_not_know(self):
        self.hero(WIZARD)
        self.assertIn("does not know", call("dnd_attack", spell="Wish", damage="1d10", ac=10))

    def test_enemy_attacks_hit_the_real_hp(self):
        self.begin()
        self.dice(15, 4)
        call("dnd_enemy_attack", enemy="Goblin", attack_bonus=4, damage="1d6+2")
        self.assertEqual(d.game()["character"]["hp"], 12 - 6)

    def test_turns_skip_the_fallen_and_give_actions_back(self):
        self.begin()
        call("dnd_combat", action="damage", target="Goblin", amount=99)
        self.assertIn("Every enemy is defeated", call("dnd_combat", action="next"))

    def test_attacks_wait_for_the_players_place_in_the_order(self):
        self.begin(goblin_first=True)
        self.assertIn("Goblin's turn", call("dnd_attack", weapon="Longsword", target="Goblin"))
        self.dice(15, 2)
        self.assertIn("HIT", call("dnd_attack", weapon="Longsword", target="Goblin", reaction=True))  # an Opportunity Attack

    def test_the_dm_cannot_play_the_players_turn(self):
        self.begin(goblin_first=True)
        self.assertIn("Brin's turn", call("dnd_combat", action="next"))        # Goblin has gone: over to the player
        self.assertIn("not said what they do", call("dnd_attack", weapon="Longsword", target="Goblin"))
        self.assertIn("not said what they do", call("dnd_combat", action="next"))
        d.dm_prompt()                                                          # the player has answered
        self.dice(10, 2)
        self.assertIn("HIT", call("dnd_attack", weapon="Longsword", target="Goblin"))

    def test_economy_is_refused_twice(self):
        self.begin()
        call("dnd_update", spend="bonus")
        self.assertIn("already used", call("dnd_update", spend="bonus action"))

    def test_nobody_rests_mid_fight(self):
        self.begin()
        self.assertIn("nobody rests", call("dnd_rest", kind="long"))


class Rest(Base):
    def test_long_rest_restores(self):
        self.hero(WIZARD)
        call("dnd_update", hp=-3, slot_used=1, exhaustion=2)
        call("dnd_rest", kind="long")
        c = d.game()["character"]
        self.assertEqual((c["hp"], c["slots"]["1"]["used"], c["exhaustion"]), (c["max_hp"], 0, 1))

    def test_short_rest_spends_hit_dice(self):
        self.hero()
        call("dnd_update", hp=-8)
        self.dice(6)
        call("dnd_rest", kind="short", hit_dice=1)
        c = d.game()["character"]
        self.assertEqual((c["hp"], c["hit_dice_spent"]), (12, 1))
        self.assertIn("only 0", call("dnd_rest", kind="short", hit_dice=1))


class Memory(Base):
    def test_notes_persist_on_disk(self):
        self.hero()
        call("dnd_record", kind="npc", name="Mira", text="innkeeper of the Gilded Goose, owes Brin a favour")
        d.GAME[0] = None
        self.assertIn("Gilded Goose", d.game()["npcs"]["Mira"]["text"])

    def test_notes_gather_rather_than_overwrite(self):
        call("dnd_record", kind="npc", name="Mira", text="innkeeper")
        call("dnd_record", kind="npc", name="mira", text="secretly a spy")
        self.assertEqual(list(d.game()["npcs"]), ["Mira"])
        self.assertIn("innkeeper secretly a spy", d.game()["npcs"]["Mira"]["text"])

    def test_every_turn_is_kept_without_the_model(self):
        d.after_turn("I open the chest", "It is full of gold.")
        self.assertEqual(d._transcript()[0]["player"], "I open the chest")
        self.assertEqual(d.game()["turns"], 1)

    def test_recall_finds_the_transcript_and_notes(self):
        call("dnd_record", kind="clue", text="the red key opens the crypt")
        d.after_turn("I ask about Vorn", "Vorn was last seen at the docks.")
        self.assertIn("docks", d.TOOLS["dnd_recall"](json.dumps({"query": "Vorn"})))
        self.assertIn("crypt", d.TOOLS["dnd_recall"](json.dumps({"query": "red key"})))

    def test_recall_says_when_something_never_happened(self):
        self.assertIn("NOTHING IN THE RECORD", d.TOOLS["dnd_recall"](json.dumps({"query": "Zanzibar"})))

    def test_the_prompt_is_built_from_the_record(self):
        self.hero()
        call("dnd_scene", location="The Gilded Goose", situation="A stranger stares")
        call("dnd_record", kind="quest", name="Find Vorn", text="He owes the guild")
        prompt = d.dm_prompt()
        for expected in ("Brin", "HP 12/12", "10 gp", "Longsword", "The Gilded Goose", "Find Vorn"):
            self.assertIn(expected, prompt)

    def test_no_character_means_session_zero(self):
        self.assertIn("session zero", d.dm_prompt())

    def test_a_damaged_save_falls_back_and_is_kept(self):
        self.hero()
        call("dnd_update", gp=1)
        Path(self.dir, "campaign.json").write_text("{not json")
        d.GAME[0] = None
        self.assertEqual(d.game()["character"]["name"], "Brin")
        self.assertTrue([f for f in os.listdir(self.dir) if "damaged" in f])

    def test_summaries_retry_after_failure(self):
        d.CHRONICLE_EVERY  # the transcript holds them until a summary succeeds
        with mock.patch.object(d, "HOST", [mock.Mock()]) as host:
            host[0].ollama.chat.side_effect = RuntimeError("no model")
            d.after_turn("a", "b")
            d._chronicle("m")
            self.assertEqual(d.game()["chronicled"], 0)
            host[0].ollama.chat.side_effect = None
            host[0].ollama.chat.return_value = {"message": {"content": "- Brin opened the chest"}}
            d._chronicle("m")
        self.assertEqual(d.game()["chronicled"], 1)
        self.assertIn("chest", d.game()["chronicle"][0]["text"])

    def test_resume_restores_the_conversation(self):
        self.hero()
        d.after_turn("I knock", "The door creaks open.")
        host = mock.Mock(HISTORY=[])
        self.assertIn("Welcome back, Brin", d.on_activate("", host))
        self.assertEqual(host.HISTORY[1]["content"], "The door creaks open.")

    def test_new_keeps_the_old_campaign(self):
        self.hero()
        call("dnd_update", gp=1)
        d.on_activate("new", mock.Mock(HISTORY=[]))
        self.assertIsNone(d.game()["character"])
        self.assertTrue(list(Path(self.dir).parent.glob(Path(self.dir).name + "-archive-*")))
        for old in Path(self.dir).parent.glob(Path(self.dir).name + "-archive-*"):
            shutil.rmtree(old)


class NamesKeptByCode(Base):
    def test_a_new_bold_name_is_kept_even_if_never_recorded(self):
        self.hero()
        d.after_turn("I look around", "A woman steps up. **Elara** grips your arm and begs for help.")
        self.assertIn("begs for help", d.game()["mentions"]["Elara"]["text"])
        self.assertIn("Elara", d.dm_prompt())
        self.assertIn("begs for help", d.TOOLS["dnd_recall"](json.dumps({"query": "Elara"})))

    def test_known_names_are_not_captured(self):
        self.hero()
        call("dnd_record", kind="npc", name="Mira", text="innkeeper")
        d.after_turn("x", "**Mira** nods. **Brin** nods back. You draw your **Longsword**.")
        self.assertEqual(d.game()["mentions"], {})

    def test_filing_a_name_takes_it_off_the_list(self):
        self.hero()
        d.after_turn("x", "**Elara** waves.")
        call("dnd_record", kind="npc", name="Elara", text="a frightened miner's daughter")
        self.assertEqual(d.game()["mentions"], {})

    def test_names_without_bold_are_caught_mid_sentence(self):
        self.hero()
        d.after_turn("x", "You walk the road towards Oakhaven, where the woman called Elara Voss once lived.")
        self.assertEqual(sorted(d.game()["mentions"]), ["Elara Voss", "Oakhaven"])

    def test_game_words_are_not_names(self):
        self.hero()
        d.after_turn("x", "You feel your Strength return, a Dwarf from the hall smiles, and said I've left on Tuesday.")
        self.assertEqual(d.game()["mentions"], {})

    def test_ordinary_emphasis_is_left_alone(self):
        self.hero()
        d.after_turn("x", "It is **not** safe here.")
        self.assertEqual(d.game()["mentions"], {})


class Builder(Base):
    def choices(self, **over):
        return {"name": "Brin", "class": "fighter", "species": "Dwarf", "background": "Soldier", "method": "array",
                "scores": dict(zip(d.ABILITIES, (15, 13, 14, 8, 12, 10))), "bonus": {"str": 2, "con": 1},
                "skills": ["perception", "survival"], "spells": [], **over}

    def test_a_fighter_comes_out_by_the_rules(self):
        ok, _message = d.create_from_builder(self.choices())
        self.assertTrue(ok)
        c = d.game()["character"]
        self.assertEqual((c["abilities"]["str"], c["abilities"]["con"]), (17, 15))
        self.assertEqual(c["max_hp"], 10 + 2 + 1)                     # d10, Con +2, Dwarven Toughness
        self.assertEqual(c["ac"], 16)                                 # Chain Mail
        self.assertEqual(c["gold"]["gp"], 54)                         # 4 from the class, 50 from the background
        self.assertEqual(set(c["skills"]), {"athletics", "intimidation", "perception", "survival"})
        self.assertTrue(d._item(c, "Greatsword")["damage"])
        self.assertIn("Savage Attacker (Origin feat)", c["features"])

    def test_every_class_can_be_built(self):
        for cls in d.CLASSES:
            count, allowed, _f, _b = d.CLASS_INFO[cls]
            skills = [s for s in allowed if s not in ("athletics", "intimidation")][:count]
            spells = []
            if cls in d.SPELL_CHOICES:
                need_c, need_l, cantrips, level_1 = d.SPELL_CHOICES[cls]
                spells = [*cantrips[:need_c], *[s for s in level_1 if s not in cantrips][:need_l]]
            args = d.build_character(self.choices(**{"class": cls, "skills": skills, "spells": spells}))
            self.assertEqual(args["class"], cls)

    def test_ac_formulas(self):
        monk = {"str": 10, "dex": 16, "con": 10, "int": 10, "wis": 14, "cha": 10}
        self.assertEqual(d.armor_class("monk", monk), 10 + 3 + 2)
        self.assertEqual(d.armor_class("cleric", monk), 13 + 2 + 2)   # Chain Shirt caps Dex at +2, then the Shield
        self.assertEqual(d.armor_class("fighter", monk), 16)          # Chain Mail ignores Dex

    def test_the_rules_are_enforced(self):
        bad = [{"scores": dict(zip(d.ABILITIES, (15, 15, 15, 8, 8, 8)))}, {"bonus": {"str": 2, "wis": 1}}, {"bonus": {"str": 3}},
               {"skills": ["perception"]}, {"skills": ["perception", "arcana"]}, {"skills": ["athletics", "perception"]}, {"name": " "}, {"class": "jedi"}]
        for change in bad:
            with self.assertRaises(d.Rejected, msg=change):
                d.build_character(self.choices(**change))

    def test_point_buy_budget(self):
        over = dict(zip(d.ABILITIES, (15, 15, 15, 15, 8, 8)))
        with self.assertRaises(d.Rejected):
            d.build_character(self.choices(method="buy", scores=over))
        fine = dict(zip(d.ABILITIES, (15, 15, 15, 8, 8, 8)))
        self.assertEqual(d.build_character(self.choices(method="buy", scores=fine))["name"], "Brin")

    def test_spell_counts_are_enforced(self):
        with self.assertRaises(d.Rejected):
            d.build_character(self.choices(**{"class": "wizard", "skills": ["arcana", "history"], "spells": ["Fire Bolt"]}))

    def test_rogues_get_expertise(self):
        c = d.build_character(self.choices(**{"class": "rogue", "skills": ["stealth", "deception", "acrobatics", "perception"]}))
        self.assertEqual(c["expertise"], ["stealth", "deception"])

    def test_rolled_scores_are_4d6_drop_lowest(self):
        self.dice(*[1, 2, 3, 4] * 6)
        self.assertEqual(d.roll_scores(), [9] * 6)

    def test_dwarven_toughness_counts_on_level_up(self):
        d.create_from_builder(self.choices())
        call("dnd_update", xp=300)
        before = d.game()["character"]["max_hp"]
        call("dnd_update", level_up=True)
        self.assertEqual(d.game()["character"]["max_hp"], before + 6 + 2 + 1)


class PlayerRolls(Base):
    def setUp(self):
        super().setUp()
        self.asked = []

        def roller(request, make):
            self.assertFalse(d.LOCK._is_owned())     # the window must be able to read the sheet while they think
            self.asked.append(request)
            return make()
        patch = mock.patch.object(d, "ROLLER", [roller])
        patch.start()
        self.addCleanup(patch.stop)

    def test_checks_wait_for_the_player(self):
        self.hero()
        self.dice(12)
        out = call("dnd_check", check="perception", dc=10, reason="Spot the thief")
        self.assertEqual(self.asked[0]["title"], "Spot the thief")
        self.assertIn("+3", self.asked[0]["detail"])
        self.assertIn("SUCCESS", out)

    def test_attacks_ask_for_to_hit_then_damage(self):
        self.hero()
        self.dice(15, 6)
        call("dnd_attack", weapon="Longsword", target="Thug", ac=10)
        self.assertEqual([r.get("damage", False) for r in self.asked], [False, True])

    def test_a_miss_asks_for_no_damage(self):
        self.hero()
        self.dice(2)
        call("dnd_attack", weapon="Longsword", target="Thug", ac=18)
        self.assertEqual(len(self.asked), 1)

    def test_advantage_shows_two_dice(self):
        self.hero()
        self.dice(4, 17)
        out = call("dnd_check", check="perception", advantage="advantage")
        self.assertEqual(self.asked[0]["count"], 2)
        self.assertIn("kept 17", out)

    def test_enemy_rolls_stay_automatic(self):
        self.hero()
        self.dice(15, 3)
        call("dnd_enemy_attack", enemy="Thug", attack_bonus=2, damage="1d6")
        self.assertEqual(self.asked, [])

    def test_walking_away_means_it_did_not_happen(self):
        self.hero()
        with mock.patch.object(d, "ROLLER", [lambda r, m: None]):
            self.assertIn("did NOT happen", call("dnd_check", check="perception"))

    def test_a_summary_finishing_during_a_roll_is_kept(self):
        self.hero()

        def roller(request, make):
            d.game()["chronicle"].append({"from": 1, "to": 1, "text": "x"})
            d.game()["chronicled"] = 1
            return make()
        with mock.patch.object(d, "ROLLER", [roller]):
            call("dnd_check", check="perception")
        self.assertEqual(d.game()["chronicled"], 1)


class Abilities(Base):
    def make(self, **over):
        base = {"name": "Brin", "class": "fighter", "species": "Dwarf", "background": "Soldier", "method": "array",
                "scores": dict(zip(d.ABILITIES, (15, 13, 14, 8, 12, 10))), "bonus": {"str": 2, "con": 1},
                "skills": ["perception", "survival"], "spells": [], **over}
        self.assertTrue(d.create_from_builder(base)[0])
        return d.game()["character"]

    def test_second_wind_heals_and_spends_a_use(self):
        self.make()
        call("dnd_update", hp=-8)
        self.dice(6)
        out = call("dnd_use_feature", name="Second Wind")
        self.assertIn("healed 7", out)
        c = d.game()["character"]
        self.assertEqual((c["hp"], c["resources"]["Second Wind"]["used"]), (12, 1))

    def test_second_wind_runs_out(self):
        self.make()
        call("dnd_update", hp=-10)
        for _ in range(2):
            self.dice(1)
            call("dnd_use_feature", name="second wind")
        self.assertIn("no uses left", call("dnd_use_feature", name="Second Wind"))

    def test_rests_give_uses_back_by_the_rules(self):
        self.make()
        d.game()["character"]["resources"]["Second Wind"]["used"] = 2
        call("dnd_rest", kind="short", hit_dice=0)
        self.assertEqual(d.game()["character"]["resources"]["Second Wind"]["used"], 1)
        call("dnd_rest", kind="long")
        self.assertEqual(d.game()["character"]["resources"]["Second Wind"]["used"], 0)

    def test_it_costs_the_bonus_action(self):
        self.make()
        call("dnd_update", hp=-8)
        self.dice(3, 15, 2)
        call("dnd_combat", action="start", enemies=[{"name": "Goblin", "hp": 7, "ac": 13}])
        call("dnd_use_feature", name="Second Wind")
        self.assertTrue(d.game()["combat"]["economy"]["bonus"])
        self.assertIn("already used", call("dnd_use_feature", name="Second Wind"))

    def test_the_unconscious_cannot_use_it(self):
        self.make()
        call("dnd_update", hp=-13)
        self.assertIn("cannot use", call("dnd_use_feature", name="Second Wind"))

    def test_you_only_have_what_is_on_the_sheet(self):
        self.make()
        self.assertIn("does not have", call("dnd_use_feature", name="Rage"))

    def test_the_prompt_lists_what_is_ready(self):
        self.make()
        self.assertIn("Second Wind (2/2)", d.dm_prompt())

    def test_narrating_it_without_the_tool_goes_back(self):
        self.make()
        with mock.patch.object(a, "CURRENT_USER_TEXT", ["I use Second Wind."]):
            self.assertTrue(any("dnd_use_feature" in p for p in d.review("You feel better.", {})))
            self.assertFalse(any("dnd_use_feature" in p for p in d.review("You feel better.", {"dnd_use_feature": 1})))

    def test_uses_grow_with_level_and_new_features_arrive(self):
        self.make()
        for xp in (300, 600, 1800):
            call("dnd_update", xp=xp, level_up=True)
        c = d.game()["character"]
        self.assertEqual(c["level"], 4)
        self.assertEqual(c["resources"]["Second Wind"]["max"], 3)
        self.assertIn("Action Surge", c["resources"])

    def test_action_surge_gives_the_action_back(self):
        self.make()
        d.game()["character"]["features"].append("Action Surge")
        d._sync_resources(d.game()["character"])
        self.dice(3, 15)
        call("dnd_combat", action="start", enemies=[{"name": "Goblin", "hp": 70, "ac": 13}])
        d.game()["combat"]["economy"]["action"] = True
        call("dnd_use_feature", name="Action Surge")
        self.assertFalse(d.game()["combat"]["economy"]["action"])

    def rager(self):
        return self.make(**{"class": "barbarian", "skills": ["perception", "survival"], "species": "Human"})

    def test_rage_hits_harder_and_halves_physical_damage(self):
        c = self.rager()
        c["inventory"][0].update(name="Greataxe")
        call("dnd_use_feature", name="Rage")
        self.dice(10, 6, 1)                                                           # Savage Attacker's second roll is lower
        self.assertIn("for 11 damage", call("dnd_attack", weapon="Greataxe", ac=5))   # 6 + Str +3 + Rage +2
        self.dice(15, 6)
        call("dnd_enemy_attack", enemy="Orc", attack_bonus=10, damage="1d6", damage_type="slashing")
        self.assertEqual(d.game()["character"]["hp"], d.game()["character"]["max_hp"] - 3)

    def test_rage_is_refused_in_heavy_armor(self):
        self.rager()
        call("dnd_inventory", add=[{"name": "Chain Mail", "equipped": True}])
        self.assertIn("heavy armor", call("dnd_use_feature", name="Rage"))

    def test_lay_on_hands_draws_on_a_pool(self):
        self.make(**{"class": "paladin", "skills": ["insight", "medicine"], "spells": ["Bless", "Command"]})
        call("dnd_update", hp=-6)
        self.assertIn("healed 3", call("dnd_use_feature", name="Lay on Hands", amount=3))
        self.assertEqual(d.game()["character"]["resources"]["Lay on Hands"]["used"], 3)

    def test_relentless_endurance_saves_an_orc_once(self):
        self.make(species="Orc")
        call("dnd_update", hp=-12)
        c = d.game()["character"]
        self.assertEqual(c["hp"], 1)
        call("dnd_update", hp=-1)
        self.assertEqual(d.game()["character"]["hp"], 0)

    def test_halfling_luck_rerolls_ones(self):
        self.make(species="Halfling")
        self.dice(1, 15)
        self.assertIn("rolled 15", call("dnd_check", check="perception"))

    def test_savage_attacker_keeps_the_better_roll(self):
        self.make()
        self.dice(15, 2, 1, 6, 3)
        self.assertIn("for 12 damage", call("dnd_attack", weapon="Greatsword", ac=5))  # the better 2d6 (9) + Str +3

    def test_humans_are_resourceful(self):
        self.make(species="Human")
        call("dnd_rest", kind="long")
        self.assertTrue(d.game()["character"]["inspiration"])

    def test_alert_helps_initiative(self):
        self.make(background="Criminal", bonus={"dex": 2, "con": 1})
        self.dice(3, 10)
        out = call("dnd_combat", action="start", enemies=[{"name": "Goblin", "hp": 7, "ac": 13}])
        self.assertIn("Brin (14)", out)                                  # d20 10, Dex +2, proficiency +2

    def test_sneak_attack_adds_dice_for_finesse(self):
        self.make(**{"class": "rogue", "skills": ["stealth", "deception", "acrobatics", "perception"], "species": "Human", "background": "Sage", "bonus": {"con": 2, "int": 1}})
        self.dice(15, 4, 5)
        self.assertIn("HIT for 11 damage", call("dnd_attack", weapon="Shortsword", ac=5, sneak=True))  # 4 + 5 + finesse +2

    def test_every_listed_feature_has_a_tooltip(self):
        for info in d.CLASS_INFO.values():
            for f in info[2]:
                self.assertIn(f, d.FEATURE_TIPS)
        for info in d.SPECIES.values():
            for f in info[1]:
                self.assertIn(f, d.FEATURE_TIPS)
        for info in d.BACKGROUNDS.values():
            self.assertIn(d.feature_key(info[1]), d.FEATURE_TIPS)
        for levels in d.PROGRESSION.values():
            for features in levels.values():
                for f in features:
                    self.assertIn(f, d.FEATURE_TIPS)
        for choice in d.SPELL_CHOICES.values():
            for spell in (*choice[2], *choice[3]):
                self.assertIn(spell, d.SPELL_TIPS)
        self.assertEqual(set(d.SKILL_TIPS), set(d.SKILLS))
        for action in d.STANDARD_ACTIONS:
            self.assertIn(action.lower(), d.RULES)


class Subclasses(Base):
    def fighter(self, level_to=3):
        Abilities.make(self)
        call("dnd_update", xp=900)
        for _ in range(level_to - 1):
            call("dnd_update", level_up=True)
        return d.game()["character"]

    make = Abilities.make

    def test_reaching_level_3_asks_for_one(self):
        c = self.fighter()
        self.assertTrue(c["needs_subclass"])
        self.assertIn("MUST CHOOSE A SUBCLASS", d.dm_prompt())

    def test_choosing_gives_the_features(self):
        self.fighter()
        call("dnd_update", subclass="champion")
        c = d.game()["character"]
        self.assertEqual(c["subclass"], "Champion")
        self.assertIn("Improved Critical", c["features"])
        self.assertNotIn("needs_subclass", c)

    def test_every_class_has_one_and_tips_for_it(self):
        self.assertEqual(set(d.SUBCLASSES), set(d.CLASSES))
        for options in d.SUBCLASSES.values():
            for name, levels in options.items():
                self.assertIn(name, d.SUBCLASS_BLURBS)
                self.assertTrue(all(f in d.FEATURE_TIPS for fs in levels.values() for f in fs))
                self.assertIn(3, levels)

    def test_not_before_level_3(self):
        self.make()
        self.assertIn("level 3", call("dnd_update", subclass="Champion"))

    def test_only_one_and_only_real_ones(self):
        self.fighter()
        self.assertIn("not a known", call("dnd_update", subclass="Space Marine"))
        call("dnd_update", subclass="Champion")
        self.assertIn("already chosen", call("dnd_update", subclass="Champion"))

    def test_improved_critical_lands_on_19(self):
        self.fighter()
        call("dnd_update", subclass="Champion")
        self.dice(19, 1, 1, 1, 1, 1, 1, 1, 1)
        self.assertIn("CRITICAL HIT", call("dnd_attack", weapon="Greatsword", ac=30))

    def test_later_features_arrive_on_level_up(self):
        self.fighter()
        call("dnd_update", subclass="Champion")
        call("dnd_update", milestone=True, level_up=True)
        for _ in range(3):
            call("dnd_update", milestone=True, level_up=True)
        self.assertEqual(d.game()["character"]["level"], 7)
        self.assertIn("Additional Fighting Style", d.game()["character"]["features"])

    def test_remarkable_athlete_gives_advantage(self):
        self.fighter()
        call("dnd_update", subclass="Champion")
        self.dice(3, 18)
        self.assertIn("kept 18", call("dnd_check", check="athletics"))

    def test_draconic_resilience(self):
        self.make(**{"class": "sorcerer", "skills": ["arcana", "deception"], "spells": ["Fire Bolt", "Light", "Mage Hand", "Mending", "Shield", "Sleep"]})
        call("dnd_update", xp=900)
        call("dnd_update", level_up=True)
        call("dnd_update", level_up=True)
        before = d.game()["character"]["max_hp"]
        call("dnd_update", subclass="Draconic Sorcery")
        self.assertEqual(d.game()["character"]["max_hp"], before + 3)

    def test_a_subclass_from_a_book_can_bring_usable_features(self):
        self.fighter()
        d.LOOKED_UP[:] = ["the battle master gains superiority dice"]
        self.addCleanup(d.LOOKED_UP.clear)
        out = call("dnd_update", subclass="Battle Master", from_book=True,
                   add_features=[{"name": "Superiority Dice", "tip": "Spend a die for a maneuver.", "uses": 4, "rest": "short", "how": "free"}])
        self.assertIn("Superiority Dice", out)
        self.assertIn("Superiority Dice (4/4)", d.dm_prompt())
        self.assertIn("3 left", call("dnd_use_feature", name="Superiority Dice"))
        self.assertEqual(d.view()["character"]["tips"]["Superiority Dice"], "Spend a die for a maneuver.")
        call("dnd_rest", kind="short", hit_dice=0)
        self.assertEqual(d.game()["character"]["resources"]["Superiority Dice"]["used"], 0)


class BooksMustBeRead(Subclasses):
    FEATURE = [{"name": "Mire Stance", "tip": "Root yourself.", "uses": 3, "rest": "short", "how": "bonus"}]

    def setUp(self):
        super().setUp()
        self.addCleanup(d.LOOKED_UP.clear)
        d.LOOKED_UP.clear()

    def test_it_must_be_looked_up_first(self):
        self.fighter()
        self.assertIn("dnd_book_search", call("dnd_update", subclass="Order of the Bog Knight", from_book=True, add_features=self.FEATURE))
        self.assertFalse(d.game()["character"].get("subclass"))

    def test_invented_features_are_refused(self):
        self.fighter()
        d.LOOKED_UP[:] = ["order of the bog knight. level 3 feature: mire stance"]
        bad = [{"name": "Bog Walker", "tip": "Ignore mud."}]
        self.assertIn("Do not make up", call("dnd_update", subclass="Order of the Bog Knight", from_book=True, add_features=bad))
        self.assertNotIn("Bog Walker", d.game()["character"]["features"])

    def test_a_subclass_the_book_does_not_have_is_refused(self):
        self.fighter()
        d.LOOKED_UP[:] = ["nothing about that here"]
        self.assertIn("not in what the books returned", call("dnd_update", subclass="Order of the Bog Knight", from_book=True, add_features=self.FEATURE))

    def test_what_the_book_says_is_accepted(self):
        self.fighter()
        d.LOOKED_UP[:] = ["order of the bog knight. level 3 feature: mire stance"]
        call("dnd_update", subclass="Order of the Bog Knight", from_book=True, add_features=self.FEATURE)
        c = d.game()["character"]
        self.assertEqual((c["subclass"], c["resources"]["Mire Stance"]["max"]), ("Order of the Bog Knight", 3))

    def test_a_new_message_needs_a_new_search(self):
        d.LOOKED_UP[:] = ["x"]
        d.dm_prompt()
        self.assertEqual(d.LOOKED_UP, [])

    def test_fights_check_the_books_first(self):
        self.make()
        with mock.patch.object(d.dnd_library, "books", lambda: [{"title": "T"}]):
            self.assertIn("dnd_book_search", call("dnd_combat", action="start", enemies=[{"name": "Goblin", "hp": 7, "ac": 13}]))
            self.assertIsNone(d.game()["combat"])
            d.LOOKED_UP[:] = [""]                                                # a search that found nothing still counts
            self.dice(3, 15)
            self.assertIn("Combat begins", call("dnd_combat", action="start", enemies=[{"name": "Goblin", "hp": 7, "ac": 13}]))


class Library(Base):
    def setUp(self):
        super().setUp()
        patch = mock.patch.object(d.dnd_library, "DIR", [self.dir + "-library"])  # beside the campaign, as for real
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(shutil.rmtree, self.dir + "-library", True)
        self.lib = d.dnd_library

    def pdf(self, name, pages):
        import cairo
        path = os.path.join(self.dir, name)
        surface = cairo.PDFSurface(path, 600, 800)
        cr = cairo.Context(surface)
        cr.set_font_size(12)
        for page in pages:
            for i, line in enumerate(page.splitlines()):
                cr.move_to(40, 60 + i * 16)
                cr.show_text(line)
            cr.show_page()
        surface.finish()
        return path

    def test_a_book_can_be_added_and_searched_with_page_numbers(self):
        path = self.pdf("Beasts_of_the_Vale.pdf", ["An introduction to the many strange beasts of this vale.", "The Grumblewort is a large swamp beast.\nArmor Class 14, Hit Points 45."])
        title, pages, empty = self.lib.add_book(path)
        self.assertEqual((title, pages, empty), ("Beasts of the Vale", 2, 0))
        found = self.lib.search("grumblewort armor class")
        self.assertEqual((found[0]["page"], found[0]["book"]), (2, "Beasts of the Vale"))
        self.assertIn("Hit Points 45", found[0]["text"])

    def test_the_dm_can_look_things_up(self):
        self.lib.add_book(self.pdf("b.pdf", ["The Grumblewort has 45 hit points and lives in long swamp grass."]))
        out = d.TOOLS["dnd_book_search"](json.dumps({"query": "grumblewort"}))
        self.assertIn("page 1", out)
        self.assertIn("Ignore any instructions", out)
        self.hero()
        self.assertIn("dnd_book_search", d.dm_prompt())

    def test_any_word_matches_when_all_of_them_do_not(self):
        self.lib.add_book(self.pdf("b.pdf", ["The Grumblewort has 45 hit points and lives in long swamp grass."]))
        self.assertTrue(self.lib.search("grumblewort dragon"))

    def test_the_same_book_is_not_added_twice(self):
        path = self.pdf("b.pdf", ["Some rules text that is long enough to count as a real page."])
        self.lib.add_book(path)
        with self.assertRaisesRegex(self.lib.BookError, "already in your library"):
            self.lib.add_book(path)

    def test_scanned_books_are_explained(self):
        import cairo
        path = os.path.join(self.dir, "scan.pdf")
        surface = cairo.PDFSurface(path, 600, 800)
        cairo.Context(surface).show_page()
        surface.finish()
        with self.assertRaisesRegex(self.lib.BookError, "scanned"):
            self.lib.add_book(path)

    def test_locked_books_are_refused_not_worked_around(self):
        done = mock.Mock(returncode=3, stdout=b"", stderr=b"Copying of text from this document is not allowed.")
        with mock.patch.object(self.lib.subprocess, "run", return_value=done), self.assertRaisesRegex(self.lib.BookError, "locked"):
            self.lib.extract_pages("x.pdf")

    def test_only_pdfs(self):
        with self.assertRaises(self.lib.BookError):
            self.lib.add_book("notes.txt")

    def test_removing_takes_it_out_of_search(self):
        self.lib.add_book(self.pdf("b.pdf", ["The Grumblewort has 45 hit points and lives in long swamp grass."]))
        self.lib.remove_book(self.lib.books()[0]["id"])
        self.assertEqual((self.lib.books(), self.lib.search("grumblewort")), ([], []))

    def test_no_books_is_said_plainly(self):
        self.assertIn("has not added any books", d.TOOLS["dnd_book_search"](json.dumps({"query": "x"})))

    def test_results_are_kept_short(self):
        self.lib.add_book(self.pdf("b.pdf", ["word " * 30 + "\n" + "\n".join("Grumblewort " * 10 for _ in range(40))]))
        self.assertLessEqual(len(self.lib.search("grumblewort")[0]["text"]), self.lib.RESULT_CHARS)

    def test_a_new_campaign_keeps_the_books(self):
        self.lib.add_book(self.pdf("b.pdf", ["The Grumblewort has 45 hit points and lives in long swamp grass."]))
        self.hero()
        d.on_activate("new", mock.Mock(HISTORY=[]))
        self.assertEqual(len(self.lib.books()), 1)
        for old in Path(self.dir).parent.glob(Path(self.dir).name + "-archive-*"):
            shutil.rmtree(old)


class Review(Base):
    def test_invented_rolls_are_caught(self):
        self.assertTrue(d.review("You rolled a 17 and the lock clicks.", {}))
        self.assertFalse(d.review("You rolled a 17 and the lock clicks.", {"dnd_check": 1}))

    def test_money_and_damage_need_a_tool(self):
        self.assertTrue(d.review("You receive 50 gold from the mayor.", {}))
        self.assertFalse(d.review("You receive 50 gold from the mayor.", {"dnd_update": 1}))
        self.assertTrue(d.review("You take 6 slashing damage.", {}))

    def test_a_reply_cannot_end_on_an_enemys_turn(self):
        self.hero()
        self.dice(15, 3)
        call("dnd_combat", action="start", enemies=[{"name": "Goblin", "hp": 7, "ac": 13, "init_bonus": 2}])
        self.assertIn("still Goblin's turn", d.review("The goblin stabs you.", {})[0])
        d.game()["combat"]["turn"] = 1
        self.assertEqual(d.review("What do you do?", {}), [])

    def test_the_fallen_can_only_make_death_saves(self):
        self.hero()
        self.dice(3, 15)
        call("dnd_combat", action="start", enemies=[{"name": "Goblin", "hp": 7, "ac": 13, "init_bonus": 2}])
        call("dnd_update", hp=-12)
        self.assertIn("death save", call("dnd_attack", weapon="Longsword", target="Goblin"))
        self.assertIn("unconscious", d.review("Your blade finds its mark!", {"dnd_attack": 1})[0])
        call("dnd_combat", action="next")
        self.assertIn("AT 0 HP", call("dnd_combat", action="next"))
        self.assertFalse(d.game()["combat"].get("awaiting_player"))

    def test_a_finished_fight_must_be_closed(self):
        self.hero()
        self.dice(15, 3)
        call("dnd_combat", action="start", enemies=[{"name": "Goblin", "hp": 7, "ac": 13, "init_bonus": 2}])
        call("dnd_combat", action="damage", target="Goblin", amount=99)
        self.assertIn("action end", d.review("It falls.", {})[0])

    def test_prices_are_not_transactions(self):
        self.assertFalse(d.review("The merchant says the sword costs 50 gold.", {}))

    def test_contradicting_the_sheet_is_caught(self):
        self.hero()
        self.assertTrue(d.review("You are at 5/12 HP.", {"dnd_update": 1}))
        self.assertFalse(d.review("You are at 12/12 HP.", {}))
        self.assertTrue(d.review("You now have 99 gold.", {"dnd_update": 1}))


class Hidden(Base):
    def test_not_listed_until_found(self):
        self.assertNotIn("dnd", agent_modes.completions())
        self.assertNotIn("/mode dnd", agent_modes.listing())
        self.assertNotIn("dnd", agent_modes.switch("dn", [])[0])

    def test_listed_once_found(self):
        self.hero()
        self.assertIn("dnd", agent_modes.completions())

    def test_tools_stay_out_of_other_modes(self):
        self.use = agent_modes.STATE.update(name="local", arg="")
        names = [s["function"]["name"] for s in a.offered_tools()]
        self.assertFalse([n for n in names if n.startswith("dnd_")])
        self.assertIn("not available", a.execute_tool("dnd_roll", "1d20"))

    def test_only_its_tools_in_the_mode(self):
        agent_modes.STATE.update(name="dnd", arg="")
        names = {s["function"]["name"] for s in a.offered_tools()}
        self.assertEqual(names, d.TOOL_NAMES)
        self.assertTrue(agent_modes.fiction())

    def test_the_real_date_stays_out_of_the_story(self):
        agent_modes.STATE.update(name="dnd", arg="")
        seen = {}

        def capture(messages, *_a):
            seen["system"] = messages[0]["content"]
            return "Done."
        with mock.patch.object(a, "_process", capture), mock.patch.object(d, "after_turn", lambda *_: None):
            a.process_prompt("hello")
        self.assertNotIn("current local date", seen["system"])

    def test_real_world_rules_are_left_out(self):
        agent_modes.STATE.update(name="dnd", arg="")
        self.assertNotIn("I could not confirm that", agent_modes.system_prompt("BASE"))

    def test_repeat_rolls_are_allowed(self):
        agent_modes.STATE.update(name="dnd", arg="")
        guard = a.LoopGuard()
        guard.after("dnd_roll", "1d20", "x")
        self.assertIsNone(guard.before("dnd_roll", "1d20"))

    def test_no_fact_check_or_footer_on_fiction(self):
        agent_modes.STATE.update(name="dnd", arg="")
        guard = a.LoopGuard()
        self.assertEqual(a.fact_check([], "x", "y" * 2000), [])
        self.assertEqual(guard.footer("You have 12345 dragons."), "")

    def test_arguments_reach_tools_whole(self):
        self.assertEqual(json.loads(a._args_text("dnd_update", {"gp": 5})), {"gp": 5})


if __name__ == "__main__":
    unittest.main()
