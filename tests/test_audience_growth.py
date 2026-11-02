from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from zoneinfo import ZoneInfo

from src.analytics import experiment
from src.analytics.momentum import MAX_BONUS, MomentumProfile
from src.analytics.scorecard import build_scorecard, update_scorecard
from src.analytics.scorer import select_best_candidates
from src.analytics.youtube_metrics import _analytics_rows, _refresh_recent_uploads, refresh_youtube_metrics
from src.config import ROOT
from src.editorial import same_story
from src.models import NewsItem
from src.processor.ai_writer import rewrite
from src.processor.template_writer import SHORT_MAX_WORDS, _clip_headline, fit_voiceover, rewrite_via_template
from src.publisher.base import PublishResult
from src.scraper import load_sources
from src.storage import Store

NOW = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)


def video(index, title="Cantora anuncia show #Shorts", views=1000, age=30.0, rss="", fmt="short", public=0):
    return dict(video_id=f"v{index}", title=title, rss_title=rss, view_count=views, public_view_count=public,
                subscribers_gained=1, content_format=fmt, analytics_collected_at=NOW.isoformat(),
                context={"published_at": (NOW - timedelta(days=age)).isoformat(), "duration_seconds": 40})


def channel(*recent):
    """A plain channel history where the typical Short gets 1000 views."""
    return [video(i, age=20 + i) for i in range(30)] + list(recent)


def item(title, summary=""):
    return NewsItem(source_id="test", source_name="Portal Teste", category="musica",
                    url=f"https://example.com/{abs(hash(title))}", title=title, summary=summary,
                    published_at=datetime.now(timezone.utc))


class MomentumTests(unittest.TestCase):
    def test_recent_hit_lifts_next_story_about_the_same_person(self):
        profile = MomentumProfile(channel(video(100, "Zé Felipe abre o jogo #Shorts", 30000, age=1.5)), now=NOW)
        heat = profile.heat("Zé Felipe responde a críticas")
        self.assertGreater(heat.bonus, 0.3)
        self.assertEqual(heat.subjects, ("ze felipe",))
        self.assertEqual(profile.heat("Anitta lança nova música").bonus, 0)

    def test_bonus_is_capped_so_a_follow_up_cannot_bury_the_next_big_story(self):
        rows = channel(*[video(100 + i, "Zé Felipe abre o jogo #Shorts", 900000, age=0.3 + 2 * i) for i in range(5)])
        self.assertLessEqual(MomentumProfile(rows, now=NOW).heat("Zé Felipe volta").bonus, MAX_BONUS)

    def test_a_hit_cools_down_within_days(self):
        title = "Zé Felipe abre o jogo #Shorts"
        fresh = MomentumProfile(channel(video(100, title, 30000, age=1)), now=NOW).heat("Zé Felipe volta")
        week = MomentumProfile(channel(video(100, title, 30000, age=7)), now=NOW).heat("Zé Felipe volta")
        month = MomentumProfile(channel(video(100, title, 30000, age=15)), now=NOW).heat("Zé Felipe volta")
        self.assertGreater(fresh.bonus, week.bonus)
        self.assertEqual(month.bonus, 0)

    def test_flop_never_penalises_and_never_goes_below_zero(self):
        profile = MomentumProfile(channel(video(100, "Zé Felipe abre o jogo #Shorts", 5, age=5)), now=NOW)
        heat = profile.heat("Zé Felipe volta")
        self.assertLess(heat.value, 0)
        self.assertEqual(heat.bonus, 0)

    def test_generic_words_are_not_subjects(self):
        rows = channel(video(100, "Luto no Brasil: cantor morre #Shorts", 90000, age=1),
                       video(101, "Rio recebe show #Shorts", 90000, age=1))
        profile = MomentumProfile(rows, now=NOW)
        for text in ("Brasil recebe turnê", "Luto: atriz morre", "Show no Rio"):
            self.assertEqual(profile.heat(text).bonus, 0, text)

    def test_common_word_opening_a_title_is_not_a_name(self):
        rows = channel(*[video(200 + i, "Cantora nova morre aos 80 #Shorts", age=25) for i in range(5)],
                       video(100, "Nova Morre em show #Shorts", 90000, age=1))
        self.assertEqual(MomentumProfile(rows, now=NOW).heat("Nova Morre de novo").bonus, 0)

    def test_words_used_all_the_time_stop_counting_as_a_subject(self):
        rows = [video(i, "Fulano Beltrano aparece #Shorts", age=20 + i) for i in range(30)]
        rows.append(video(100, "Fulano Beltrano abre o jogo #Shorts", 90000, age=1))
        self.assertEqual(MomentumProfile(rows, now=NOW).heat("Fulano Beltrano volta").bonus, 0)

    def test_young_low_video_is_unknown_not_cold(self):
        rows = channel(video(100, "Zé Felipe abre o jogo #Shorts", 30000, age=3),
                       video(101, "Zé Felipe de novo #Shorts", 10, age=0.1))
        with_young = MomentumProfile(rows, now=NOW).heat("Zé Felipe volta")
        alone = MomentumProfile(channel(rows[-2]), now=NOW).heat("Zé Felipe volta")
        self.assertEqual(round(with_young.value, 6), round(alone.value, 6))

    def test_third_story_in_a_day_earns_no_push(self):
        title = "Zé Felipe abre o jogo #Shorts"
        one = MomentumProfile(channel(video(100, title, 30000, age=0.5)), now=NOW).heat("Zé Felipe volta")
        two = MomentumProfile(channel(video(100, title, 30000, age=0.5), video(101, title, 30000, age=0.7)),
                              now=NOW).heat("Zé Felipe volta")
        self.assertGreater(one.bonus, 0)
        self.assertEqual(two.bonus, 0)

    def test_only_shorts_count_and_live_counter_beats_lagging_analytics(self):
        long_hit = video(100, "Zé Felipe abre o jogo", 90000, age=1, fmt="long")
        self.assertEqual(MomentumProfile(channel(long_hit), now=NOW).heat("Zé Felipe volta").bonus, 0)
        lagging = video(101, "Zé Felipe abre o jogo #Shorts", 0, age=0.7, public=40000)
        self.assertGreater(MomentumProfile(channel(lagging), now=NOW).heat("Zé Felipe volta").bonus, 0)

    def test_rss_title_links_a_rewritten_youtube_title_to_the_same_person(self):
        row = video(100, "O cantor sertanejo voltou #Shorts", 30000, age=1, rss="Zé Felipe volta após polêmica")
        self.assertGreater(MomentumProfile(channel(row), now=NOW).heat("Zé Felipe responde").bonus, 0)

    def test_too_little_history_means_no_signal(self):
        rows = [video(i, age=10) for i in range(3)] + [video(100, "Zé Felipe abre #Shorts", 90000, age=1)]
        self.assertEqual(MomentumProfile(rows, now=NOW).heat("Zé Felipe volta").bonus, 0)

    def test_missing_or_broken_rows_are_ignored(self):
        rows = channel({"video_id": "x", "title": "Zé Felipe", "content_format": "short"},
                       {"title": "no id"},
                       {**video(5), "context": {"published_at": "garbage"}})
        self.assertEqual(MomentumProfile(rows, now=NOW).heat("Zé Felipe volta").bonus, 0)

    def test_hot_subjects_lists_what_is_earning_a_bonus(self):
        profile = MomentumProfile(channel(video(100, "Zé Felipe abre o jogo #Shorts", 30000, age=1)), now=NOW)
        self.assertEqual([row["subject"] for row in profile.hot_subjects()], ["ze felipe"])


class FakeStore:
    def __init__(self, examples):
        self.examples = examples

    def analytics_examples(self, limit):
        return self.examples

    def record_candidate_scores(self, **kwargs):
        self.recorded = kwargs


class SelectionTests(unittest.TestCase):
    def rows(self, *recent):
        now = datetime.now(timezone.utc)
        out = []
        for row in channel(*recent):
            row = dict(row)
            row["source_id"] = "test"
            row["category"] = "musica"
            row["analytics_collected_at"] = now.isoformat()
            age = (NOW - datetime.fromisoformat(row["context"]["published_at"])).total_seconds()
            row["context"] = {"published_at": (now - timedelta(seconds=age)).isoformat(), "duration_seconds": 40}
            out.append(row)
        return out

    def test_follow_up_of_a_hit_wins_an_otherwise_even_slot(self):
        store = FakeStore(self.rows(video(100, "Zé Felipe abre o jogo #Shorts", 30000, age=1)))
        follow_up, other = item("Zé Felipe responde a críticas"), item("Marcos Vinicius responde a críticas")
        chosen = select_best_candidates([other, follow_up], store, limit=1, stage="fresh:video")
        self.assertEqual(chosen, [follow_up])
        reason = next(r for candidate, _, r in store.recorded["scores"] if candidate is follow_up)
        self.assertIn("subjects=ze_felipe", reason)
        self.assertNotIn("momentum=0.00", reason)

    def test_a_big_fresh_tragedy_about_someone_new_still_beats_a_follow_up(self):
        store = FakeStore(self.rows(video(100, "Zé Felipe abre o jogo #Shorts", 90000, age=1)))
        follow_up = item("Zé Felipe posta música nova")
        tragedy = item("Sahara Ray, ex-affair de Justin Bieber, morre aos 34", "Estado grave e luto da família.")
        chosen = select_best_candidates([follow_up, tragedy], store, limit=1, stage="fresh:video")
        self.assertEqual(chosen, [tragedy])

    def test_eligibility_still_has_the_last_word(self):
        store = FakeStore(self.rows(video(100, "Zé Felipe abre o jogo #Shorts", 30000, age=1)))
        follow_up, other = item("Zé Felipe responde a críticas"), item("Marcos Vinicius responde a críticas")
        chosen = select_best_candidates([follow_up, other], store, limit=1, stage="fresh:video",
                                        eligibility=lambda candidate: candidate is other)
        self.assertEqual(chosen, [other])

    def test_long_form_bulletins_are_untouched(self):
        store = FakeStore(self.rows(video(100, "Zé Felipe abre o jogo #Shorts", 30000, age=1)))
        select_best_candidates([item("Zé Felipe responde")], store, limit=1, stage="daily_music_news")
        self.assertIn("momentum=0.00", store.recorded["scores"][0][2])

    def test_signal_failure_never_stops_selection(self):
        candidate = item("Zé Felipe responde")
        for target in ("__init__", "heat"):
            store = FakeStore(self.rows())
            with self.subTest(target), mock.patch(f"src.analytics.scorer.MomentumProfile.{target}",
                                                  side_effect=RuntimeError("boom")):
                self.assertEqual(select_best_candidates([candidate], store, limit=1, stage="fresh:video"), [candidate])


class ShortScriptTests(unittest.TestCase):
    LONG = ("A cantora confirmou a turnê durante uma entrevista ao vivo na noite de ontem em São Paulo. "
            "Os ingressos começam a ser vendidos na próxima semana em todas as capitais do país, com preços populares. "
            "Segundo a produção, o repertório terá sucessos antigos e faixas inéditas do novo álbum da artista, "
            "gravado em Salvador durante o último verão com convidados especiais e a banda completa de sempre.")

    def test_script_opens_on_the_news_within_the_limit_without_filler(self):
        title = "Anitta confirma turnê no Brasil"
        post = rewrite_via_template(item(title, self.LONG), short_form=True)
        words = post.script_voiceover.split()
        self.assertLessEqual(len(words), SHORT_MAX_WORDS)
        self.assertTrue(post.script_voiceover.startswith(title))
        for filler in ("Atencao para", "O mundo da musica parou", "Acompanhe as proximas"):
            self.assertNotIn(filler, post.script_voiceover)
        self.assertIn(post.script_voiceover[-1], ".!?")

    def test_script_never_stops_in_the_middle_of_a_sentence(self):
        first, second = self.LONG.split(". ")[:2]
        self.assertEqual(fit_voiceover(self.LONG, 40), f"{first}. {second}.")
        self.assertEqual(fit_voiceover(self.LONG, 20), f"{first}.")

    def test_cuts_at_a_clause_only_when_no_whole_sentence_fits(self):
        text = "Uma frase muito longa sobre a cantora e a banda inteira, " + "que continua sem parar " * 20 + "até o fim."
        self.assertEqual(fit_voiceover(text, 20), "Uma frase muito longa sobre a cantora e a banda inteira.")
        kept_then_cut = "Primeira frase completa. De acordo com a ex-Fazenda, " + "muitas palavras seguem aqui " * 10 + "fim."
        self.assertEqual(fit_voiceover(kept_then_cut, 20), "Primeira frase completa.")

    def test_story_with_a_few_words_of_facts_adds_the_source(self):
        post = rewrite_via_template(item("Anitta lança música nova hoje em São Paulo e surpreende fãs",
                                         "A cantora publicou o anúncio nas redes sociais."), short_form=True)
        self.assertIn("A informação foi publicada por Portal Teste.", post.script_voiceover)
        self.assertGreaterEqual(len(post.script_voiceover.split()), 22)

    def test_bare_headline_keeps_the_longer_script_because_tiny_narration_breaks_the_render(self):
        post = rewrite_via_template(item("Anitta lança música"), short_form=True)
        self.assertTrue(post.script_voiceover.startswith("Atencao para esta noticia"))
        self.assertGreaterEqual(len(post.script_voiceover.split()), 18)

    def test_one_long_sentence_after_the_headline_is_kept_whole(self):
        long_sentence = " ".join(["palavra"] * 52) + " final."
        title = "Anitta lança turnê nova pelo Brasil"
        script = rewrite_via_template(item(title, long_sentence), short_form=True).script_voiceover
        self.assertTrue(script.endswith("palavra final."))
        self.assertLessEqual(len(script.split()), 72)

    def test_summary_repeating_the_title_is_not_read_twice(self):
        title = "Anitta lança música nova hoje"
        post = rewrite_via_template(item(title, title + "."), short_form=True)
        self.assertEqual(post.script_voiceover.count(title), 1)

    def test_previous_script_is_unchanged_for_control_group_and_long_form(self):
        post = rewrite_via_template(item("Anitta lança música", self.LONG))
        self.assertTrue(post.script_voiceover.startswith("Atencao para esta noticia da musica"))
        self.assertLessEqual(len(post.script_voiceover.split()), 88)

    def test_headline_is_not_cut_on_a_dangling_word(self):
        title = "MC Paiva e Soso Careca anunciam que estão à espera do primeiro filho do casal famoso"
        self.assertEqual(_clip_headline(title, 70), "MC Paiva e Soso Careca anunciam que estão à espera do primeiro filho")
        self.assertEqual(_clip_headline("Curto", 70), "Curto")

    def test_headline_is_never_empty(self):
        self.assertTrue(_clip_headline("— " + "x" * 120, 90))

    def test_headline_does_not_end_inside_an_open_quote(self):
        title = "Sonia Abrão detona sertanejo por divórcio polêmico que abalou a web: “Vamos ter muito o que falar sobre isso”"
        self.assertEqual(_clip_headline(title, 90), "Sonia Abrão detona sertanejo por divórcio polêmico que abalou a web")

    def test_headline_keeps_the_news_that_comes_after_an_apposition(self):
        title = "Cassandra Wilson, cantora de jazz ganhadora de Grammy, morre aos 70 anos"
        self.assertEqual(rewrite_via_template(item(title), short_form=True).headline, title)
        longer = "Cassandra Wilson, cantora de jazz ganhadora de Grammy e referência mundial, morre aos 70 anos em Nova York"
        self.assertIn("morre", _clip_headline(longer, 90))

    def test_ai_writer_output_is_held_to_the_same_length(self):
        long_post = rewrite_via_template(item("Anitta lança música", self.LONG))
        long_post = long_post.model_copy(update={"script_voiceover": self.LONG * 2})
        env = {"REWRITE_PROVIDER": "", "LOCAL_CLAUDE_FALLBACK": ""}
        with mock.patch.dict("os.environ", env), \
                mock.patch("src.processor.ai_writer._rewrite_via_anthropic", return_value=long_post) as ai:
            post = rewrite(item("Anitta lança música"), short_form=True)
        self.assertTrue(ai.call_args.kwargs["short_form"])
        self.assertLessEqual(len(post.script_voiceover.split()), SHORT_MAX_WORDS)

    def test_default_rewrite_stays_long_for_daily_bulletin(self):
        with mock.patch.dict("os.environ", {"REWRITE_PROVIDER": "template"}):
            post = rewrite(item("Anitta lança música", self.LONG))
        self.assertTrue(post.script_voiceover.startswith("Atencao"))


class ExperimentTests(unittest.TestCase):
    def store(self, disabled=False):
        store = mock.Mock()
        store.growth_factor_disabled.return_value = disabled
        return store

    def test_same_slot_same_arm_and_about_a_fifth_in_control(self):
        tz = ZoneInfo("America/Sao_Paulo")
        slots = [datetime(2026, 11, 2, hour, 13, tzinfo=tz) + timedelta(days=day)
                 for day in range(27) for hour in (9, 14, 19)]
        arms = [experiment.script_arm(self.store(), now=slot) for slot in slots]
        self.assertEqual(arms, [experiment.script_arm(self.store(), now=slot) for slot in slots])
        self.assertEqual(experiment.script_arm(self.store(), now=slots[0]),
                         experiment.script_arm(self.store(), now=slots[0] + timedelta(minutes=30)))
        share = arms.count(experiment.ARM_CONTROL) / len(arms)
        self.assertGreater(share, 0.08)
        self.assertLess(share, 0.35)

    def test_explicit_setting_wins_even_after_the_test_ends(self):
        late = datetime(2027, 1, 5, 9, 13, tzinfo=ZoneInfo("America/Sao_Paulo"))
        with mock.patch.dict("os.environ", {"SHORT_SCRIPT_HOLDOUT_SHARE": "1"}):
            self.assertEqual(experiment.script_arm(self.store(), now=late), experiment.ARM_CONTROL)
        with mock.patch.dict("os.environ", {"SHORT_SCRIPT_HOLDOUT_SHARE": "0"}):
            self.assertEqual(experiment.script_arm(self.store(), now=late), experiment.ARM_SHORT)

    def test_everyone_gets_the_short_script_after_the_test_ends(self):
        tz = ZoneInfo("America/Sao_Paulo")
        for day in range(1, 60):
            slot = datetime(2026, 11, 30, 9, 13, tzinfo=tz) + timedelta(days=day)
            self.assertEqual(experiment.script_arm(self.store(), now=slot), experiment.ARM_SHORT)

    def test_guard_puts_every_short_back_on_the_previous_script(self):
        slot = datetime(2026, 11, 2, 9, 13, tzinfo=timezone.utc)
        self.assertEqual(experiment.script_arm(self.store(disabled=True), now=slot), experiment.ARM_CONTROL)


def assignment(index, arm, views, *, age=10):
    return dict(video_id=f"a{index}", script_arm=arm, script_words=60, views_7d=views, views=views + 5,
                subscribers_gained=1, context={"avg_view_pct": 70.0},
                assigned_at=(NOW - timedelta(days=age)).replace(tzinfo=None).isoformat())


class ScorecardTests(unittest.TestCase):
    def rows(self, short, control, n=12):
        return ([assignment(i, "short", short) for i in range(n)]
                + [assignment(100 + i, "control", control) for i in range(n)])

    def test_clear_harm_is_detected(self):
        self.assertTrue(build_scorecard(self.rows(100, 1000), now=NOW)["harm"])

    def test_small_groups_never_trigger_the_guard(self):
        self.assertFalse(build_scorecard(self.rows(100, 1000, n=9), now=NOW)["harm"])
        self.assertTrue(build_scorecard(self.rows(100, 1000, n=10), now=NOW)["harm"])

    def test_gain_or_small_difference_is_not_harm(self):
        self.assertFalse(build_scorecard(self.rows(2000, 1000), now=NOW)["harm"])
        self.assertFalse(build_scorecard(self.rows(900, 1000), now=NOW)["harm"])

    def test_one_lucky_control_hit_alone_does_not_trigger_the_guard(self):
        rows = self.rows(1000, 1000)
        rows[-1]["views_7d"] = 500000
        self.assertFalse(build_scorecard(rows, now=NOW)["harm"])

    def test_shorts_after_the_control_group_ended_are_not_compared_with_it(self):
        rows = [assignment(100 + i, "control", 1000, age=30) for i in range(12)]
        rows += [assignment(i, "short", 100, age=8) for i in range(12)]
        after_the_test = datetime(2027, 1, 20, 12, tzinfo=timezone.utc)
        for row in rows:
            days = 70 if row["script_arm"] == "control" else 10
            row["assigned_at"] = (after_the_test - timedelta(days=days)).replace(tzinfo=None).isoformat()
        card = build_scorecard(rows, now=after_the_test)
        self.assertEqual(card["arms"]["short"]["n"], 0)
        self.assertFalse(card["harm"])

    def test_videos_younger_than_a_week_wait(self):
        rows = [assignment(i, "short", 10, age=2) for i in range(20)]
        card = build_scorecard(rows, now=NOW)
        self.assertEqual(card["mature"], 0)
        self.assertEqual(card["arms"]["short"]["n"], 0)

    def test_update_writes_file_and_switches_off_once(self):
        with TemporaryDirectory() as tmp:
            store = mock.Mock()
            store.growth_assignment_rows.return_value = self.rows(100, 1000)
            store.growth_factor_disabled.return_value = False
            with mock.patch("src.notify.notify_urgent", return_value=True) as urgent:
                update_scorecard(store, Path(tmp), now=NOW)
                store.growth_factor_disabled.return_value = True
                update_scorecard(store, Path(tmp), now=NOW)
            store.disable_growth_factor.assert_called_once_with(experiment.SHORT_SCRIPT)
            urgent.assert_called_once()
            self.assertEqual(urgent.call_args.kwargs["kind"], "growth_guard")
            saved = json.loads((Path(tmp) / "analytics" / "growth-scorecard.json").read_text())
            self.assertTrue(saved["harm"])


class StorageTests(unittest.TestCase):
    def test_snapshots_keep_history_and_real_fingerprint(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.db")
            store.record_youtube_growth_metrics(fingerprint="real-fp", video_id="vid", view_count=10,
                                               subscribers_gained=1, title="Antes", content_format="short")
            store.record_view_snapshots([{"video_id": "vid", "view_count": 50, "like_count": 3, "comment_count": 1,
                                          "title": None, "content_format": None}])
            store.record_view_snapshots([{"video_id": "new", "view_count": 7, "title": "Novo #Shorts",
                                          "content_format": "short"}])
            rows = {row["video_id"]: row for row in store.analytics_examples(None)}
            self.assertEqual(rows["vid"]["fingerprint"], "real-fp")
            self.assertEqual(rows["vid"]["public_view_count"], 50)
            self.assertEqual(rows["vid"]["view_count"], 10)
            self.assertEqual(rows["vid"]["title"], "Antes")
            self.assertEqual(rows["new"]["fingerprint"], "youtube:new")
            with store._conn() as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM youtube_view_snapshots").fetchone()[0], 2)

    def test_context_refreshes_do_not_erase_each_other(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.db")
            store.record_youtube_growth_metrics(fingerprint="f", video_id="vid", view_count=10,
                                               subscribers_gained=1, title="T #Shorts", content_format="short")
            store.record_youtube_context("vid", {"avg_view_pct": 70.0, "published_at": "old"})
            store.record_youtube_context("vid", {"published_at": "new"})
            context = store.analytics_examples(None)[0]["context"]
            self.assertEqual(context, {"avg_view_pct": 70.0, "published_at": "new"})

    def test_assignment_outcome_uses_the_seven_day_snapshot(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.db")
            store.record_growth_assignment(video_id="vid", fingerprint="f", script_arm="short", script_words=55)
            store.record_growth_assignment(video_id="vid", fingerprint="f", script_arm="control", script_words=88)
            assigned = datetime.utcnow()
            with store._conn() as conn:
                for days, views in [(1, 500), (6, 900), (8, 1000), (20, 1500)]:
                    conn.execute("INSERT INTO youtube_view_snapshots VALUES (?, ?, ?, 0, 0)",
                                 ("vid", (assigned + timedelta(days=days)).isoformat(), views))
            rows = store.growth_assignment_rows()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["script_arm"], "short")
            self.assertEqual(rows[0]["views_7d"], 1000)

    def test_guard_state_survives_restart(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.db"
            self.assertFalse(Store(path).growth_factor_disabled("short_script"))
            Store(path).disable_growth_factor("short_script")
            self.assertTrue(Store(path).growth_factor_disabled("short_script"))


class RecentUploadTests(unittest.TestCase):
    def service(self, channel_id="UC-TFUUc4YHleNoIFXBVaj7A"):
        data = mock.Mock()
        data.channels().list().execute.return_value = {"items": [{
            "id": channel_id, "contentDetails": {"relatedPlaylists": {"uploads": "up"}}}]}
        data.playlistItems().list().execute.return_value = {"items": [
            {"contentDetails": {"videoId": "a"}}, {"contentDetails": {"videoId": "b"}},
            {"contentDetails": {"videoId": "hidden"}}]}
        return data

    def test_live_counts_are_stored_and_hidden_counters_are_not_zero(self):
        data = self.service()
        data.videos().list().execute.return_value = {"items": [
            {"id": "a", "statistics": {"viewCount": "1200", "likeCount": "9", "commentCount": "2"}},
            {"id": "b", "statistics": {"viewCount": "30"}},
            {"id": "hidden", "statistics": {}}]}
        store = mock.Mock()
        meta = {"a": {"title": "A #Shorts", "content_format": "short", "published_at": "2026-11-01T10:00:00Z"}}
        with mock.patch("src.analytics.youtube_metrics._video_metadata", return_value=meta):
            self.assertEqual(_refresh_recent_uploads(store, data), 2)
        saved = store.record_view_snapshots.call_args.args[0]
        self.assertEqual({row["video_id"] for row in saved}, {"a", "b"})
        self.assertEqual(saved[0]["view_count"], 1200)
        self.assertEqual(saved[0]["title"], "A #Shorts")
        store.record_youtube_context.assert_called_once_with("a", meta["a"])

    def test_wrong_channel_writes_nothing(self):
        store = mock.Mock()
        with self.assertRaisesRegex(RuntimeError, "different channel"):
            _refresh_recent_uploads(store, self.service("other"))
        store.record_view_snapshots.assert_not_called()

    def test_recent_refresh_failure_does_not_escape_and_scorecard_still_runs(self):
        store = mock.Mock()
        store.youtube_metric_targets.return_value = []
        credentials = mock.Mock(scopes=[])
        with mock.patch("src.analytics.youtube_metrics._oauth_credentials", return_value=credentials), \
                mock.patch("src.analytics.youtube_metrics._data_service", return_value=mock.Mock()), \
                mock.patch("src.analytics.youtube_metrics._analytics_service", return_value=None), \
                mock.patch("src.analytics.youtube_metrics._refresh_recent_uploads", side_effect=RuntimeError("quota")), \
                mock.patch("src.analytics.scorecard.update_scorecard") as card:
            refresh_youtube_metrics(store)
        card.assert_called_once()

    def test_retention_is_parsed_when_the_report_has_it(self):
        response = {"columnHeaders": [{"name": n} for n in
                                      ("video", "views", "subscribersGained", "averageViewPercentage", "averageViewDuration")],
                    "rows": [["a", 100, 2, 71.5, 20]]}
        self.assertEqual(_analytics_rows(response)[0]["avg_view_pct"], 71.5)


class SameStoryTests(unittest.TestCase):
    def test_one_event_from_two_outlets_is_one_story(self):
        for first, second in [
            ("Frank Aguiar chora morte do pai e desabafa", "Frank Aguiar chora ao vivo ao anunciar morte do pai"),
            ("Lady Gaga e Michael Polansky tiveram primeira filha", "Lady Gaga e Michael Polansky são pais de uma filha"),
            ("Morre Mulher Banana, veterana do funk e ex-Furacão 2000", "Morre Mulher Banana, ícone do funk da Furacão 2000"),
        ]:
            self.assertTrue(same_story(first, second), first)

    def test_new_development_about_the_same_person_is_a_different_story(self):
        self.assertFalse(same_story("Zé Felipe e Virginia Fonseca voltam? Poliana Rocha é questionada",
                                    "Reconciliação? Zé Felipe abre o jogo sobre relação com Virginia"))
        self.assertFalse(same_story("Macklemore anuncia turnê após ser afastado de festival",
                                    "Macklemore esgota ingressos para shows"))

    def test_two_letter_first_name_counts_and_one_word_artists_need_more_shared_words(self):
        self.assertTrue(same_story("Zé Felipe anuncia música nova com Ana Castela",
                                   "Zé Felipe lança música nova com Ana Castela"))
        self.assertTrue(same_story("Anitta cancela turnê europeia após problema de saúde",
                                   "Anitta cancela turnê europeia por causa de saúde"))
        self.assertFalse(same_story("Anitta chora em show", "Anitta cancela show"))

    def test_anonymous_headlines_that_look_alike_are_not_judged(self):
        self.assertFalse(same_story("Luto: Cantor sertanejo amado pelo Brasil morre aos 38 após infarto",
                                    "Luto: Cantor amado do Brasil morre aos 84 anos e gera comoção"))
        self.assertFalse(same_story("", "Anitta lança música"))

    def test_recent_titles_cover_this_runner_and_other_uploads_only_inside_the_window(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.db")
            news = item("Anitta lança música nova")
            store.record_item_features(news)
            store.record_publication(news.fingerprint(), "youtube", "local", "ok")
            store.record_publication("failed", "youtube", "bad", "error")
            now = datetime.now(timezone.utc)
            for video_id, hours in (("other", 5), ("old", 60)):
                store.record_view_snapshots([{"video_id": video_id, "view_count": 1, "content_format": "short",
                                              "title": f"Titulo {video_id} #Shorts"}])
                store.record_youtube_context(video_id, {"published_at": (now - timedelta(hours=hours)).isoformat()})
            self.assertEqual(store.recent_short_titles(36), ["Anitta lança música nova", "Titulo other #Shorts"])


class ShortsSourcesTests(unittest.TestCase):
    def test_feed_list_keeps_daily_bulletin_separate_and_limits_the_largest_feed(self):
        sources = {source.id: source for source in load_sources(ROOT / "config" / "shorts_sources.yaml")}
        self.assertEqual(set(sources), {"ego", "otvfoco", "leodias", "metropoles", "popline", "papelpop", "quem"})
        self.assertEqual(sources["quem"].max_entries, 30)
        self.assertEqual(sources["quem"].summary_chars, 220)
        self.assertIsNone(sources["ego"].max_entries)
        daily = {source.id for source in load_sources(ROOT / "config" / "sources.yaml")}
        self.assertIn("extra_famosos", daily)

    def test_collect_respects_per_source_limits(self):
        from src.scraper.rss import collect_news
        from src.scraper.sources import Source

        entries = [{"link": f"https://example.com/{i}", "title": f"Titulo {i}", "summary": "x" * 500,
                    "published_parsed": None} for i in range(5)]
        feed = mock.Mock(entries=entries)
        source = Source(id="s", name="S", type="rss", url="https://example.com/feed", category="fofoca",
                        summary_chars=100, max_entries=2)
        with mock.patch("src.scraper.rss.feedparser.parse", return_value=feed):
            items = collect_news([source], enrich=False)
        self.assertEqual(len(items), 2)
        self.assertEqual(len(items[0].summary), 100)


class FeedTextTests(unittest.TestCase):
    def collect(self, title, summary, **source):
        from src.scraper.rss import collect_news
        from src.scraper.sources import Source

        feed = mock.Mock(entries=[{"link": "https://example.com/a", "title": title, "summary": summary,
                                   "published_parsed": None}])
        with mock.patch("src.scraper.rss.feedparser.parse", return_value=feed):
            return collect_news([Source(id="s", name="S", type="rss", url="https://example.com/f",
                                        category="fofoca", **source)], enrich=False)[0]

    def test_captions_never_reach_title_or_narration(self):
        real_hugo_gloss = ("Mulher Banana, conhecida pelo sucesso na Furacão 2000, é encontrada morta em casa "
                           "aos 49 anos mulher banana (foto_ reprodução_instagram; furacao 2000)")
        self.assertEqual(self.collect(real_hugo_gloss, "x").title,
                         "Mulher Banana, conhecida pelo sucesso na Furacão 2000, é encontrada morta em casa aos 49 anos")
        self.assertEqual(self.collect("Gracyanne cobra Belo: “Me tira”; assista (Foto:  Globo/ Beat", "x").title,
                         "Gracyanne cobra Belo: “Me tira”; assista")
        self.assertEqual(self.collect("Normal &#8220;citado&#8221; titulo", "x").title, "Normal “citado” titulo")

    def test_feed_furniture_is_removed_from_summary(self):
        for raw, expected in [
            ("Ela fez sucesso nos anos 2000 O post Mulher Banana morre apareceu primeiro em Hugo Gloss .",
             "Ela fez sucesso nos anos 2000"),
            ("(Foto: Instagram @jao) A segunda parada foi no Rio.", "A segunda parada foi no Rio."),
            ("Crédito: Divulgação As DJs lançaram uma live.", "As DJs lançaram uma live."),
            ("Capa do álbum de Fulana Divulgação ♫ NOTÍCIA ♬ Novembro chega com disco.", "Novembro chega com disco."),
        ]:
            self.assertEqual(self.collect("T", raw).summary, expected, raw)

    def test_more_caption_forms_are_removed_from_titles(self):
        self.assertEqual(self.collect("Anitta entra na Justiça após fala Foto: Globo/Angélica; Reprodução/Bacci", "x").title,
                         "Anitta entra na Justiça após fala")
        self.assertEqual(self.collect("Rayane toma atitude na web (Reprodução/TV Globo)", "x").title, "Rayane toma atitude na web")
        self.assertEqual(self.collect("Drake se manifesta Drake se manifesta", "x").title, "Drake se manifesta")
        self.assertEqual(self.collect("Anitta posta foto: veja a imagem", "x").title, "Anitta posta foto: veja a imagem")

    def test_footer_pattern_does_not_eat_ordinary_text(self):
        for raw in ("A cantora desabafou em um novo post nas redes.", "No post, ela agradeceu aos fãs.",
                    "O post de Anitta viralizou na web e teve milhões de curtidas."):
            self.assertEqual(self.collect("T", raw).summary, raw)
        self.assertEqual(
            self.collect("T", "A cantora desabafou em um novo post nas redes. O post Anitta chora apareceu primeiro em Site Y .").summary,
            "A cantora desabafou em um novo post nas redes.")

    def test_g1_photo_caption_and_credit_are_not_narrated(self):
        raw = ('<img src="https://x/y.jpg" /><br />     Heidi Klum durante sua festa de Halloween\nNoam Galai/AFP\n'
               "A modelo Heidi Klum chamou a atenção na noite de sábado.\nEla surpreendeu convidados.")
        self.assertEqual(self.collect("T", raw).summary, "A modelo Heidi Klum chamou a atenção na noite de sábado. Ela surpreendeu convidados.")
        column = ('<img src="https://x/y.jpg" /><br /> Capa do álbum\nMaria Magalhães / Divulgação\n♫ NOTÍCIA\n♬ Em cena desde 2006, ela chega aos 20 anos.')
        self.assertEqual(self.collect("T", column).summary, "Em cena desde 2006, ela chega aos 20 anos.")
        no_caption = '<img src="https://x/y.jpg" /><br /> A cantora publicou o vídeo.\nDepois ela comentou o caso na web.\nE seguiu.'
        self.assertIn("A cantora publicou o vídeo.", self.collect("T", no_caption).summary)

    def test_description_from_the_article_page_is_cleaned_too(self):
        from src.scraper.rss import _enrich_with_og

        page = mock.Mock(status_code=200, text='<meta property="og:description" content="A cantora falou sobre o caso em entrevista ao vivo nesta semana. Depois ela [...]">')
        client = mock.Mock()
        client.get.return_value = page
        enriched = _enrich_with_og(item("Anitta fala"), client)
        self.assertEqual(enriched.summary, "A cantora falou sobre o caso em entrevista ao vivo nesta semana.")

    def test_cut_summary_ends_on_a_finished_sentence(self):
        first = "A cantora confirmou tudo em entrevista ao vivo nesta segunda-feira."
        tail = "Depois ela ainda falou sobre muitos outros assuntos que ficam pela metade"
        self.assertEqual(self.collect("T", f"{first} {tail} […]").summary, first)
        self.assertEqual(self.collect("T", f"{first} {tail * 3}", summary_chars=100).summary, first)
        long_first = "Uma frase bem comprida " * 12 + "que termina aqui. Outra."
        self.assertTrue(self.collect("T", long_first, summary_chars=100).summary.endswith("termina aqui."))

    def test_wordpress_excerpt_loses_its_unfinished_last_sentence(self):
        raw = ("Liniker foi a grande surpresa do show de Jão no Rio. A cantora apareceu durante a performance e "
               "O post Jão e Liniker apareceu primeiro em PAPELPOP .")
        self.assertEqual(self.collect("T", raw).summary, "Liniker foi a grande surpresa do show de Jão no Rio.")

    def test_narration_never_ends_on_a_dangling_word(self):
        self.assertEqual(fit_voiceover("A cantora apareceu durante a performance de hoje e"),
                         "A cantora apareceu durante a performance de hoje.")

    def test_complete_summary_without_a_final_period_is_kept_and_closed_when_spoken(self):
        summary = "A cantora publicou no Instagram um vídeo longo sobre a carreira e os próximos passos"
        item_ = self.collect("Anitta lança música nova e fala sobre a turnê pelo Brasil", summary)
        self.assertEqual(item_.summary, summary)
        script = rewrite_via_template(item_, short_form=True).script_voiceover
        self.assertIn("próximos passos.", script)


class PipelineWiringTests(unittest.TestCase):
    def test_assignment_only_for_a_new_youtube_upload_and_failure_is_swallowed(self):
        from src import pipeline

        post = mock.Mock(script_voiceover="uma duas tres")
        news = item("Anitta lança")
        store = mock.Mock()
        ok = PublishResult(platform="youtube", ok=True, remote_id="vid")
        pipeline._record_growth_assignment(store, news, post, ok, "short")
        store.record_growth_assignment.assert_called_once_with(
            video_id="vid", fingerprint=news.fingerprint(), script_arm="short", script_words=3)
        store.reset_mock()
        for other in (PublishResult(platform="telegram", ok=True, remote_id="x"),
                      PublishResult(platform="youtube", ok=False, remote_id=None),
                      PublishResult(platform="youtube", ok=True, remote_id="old", reused_existing=True)):
            pipeline._record_growth_assignment(store, news, post, other, "short")
        store.record_growth_assignment.assert_not_called()
        store.record_growth_assignment.side_effect = RuntimeError("db locked")
        pipeline._record_growth_assignment(store, news, post, ok, "short")

    def test_yesterday_fallback_also_skips_a_story_just_published(self):
        from src import pipeline

        yesterday = datetime.now(ZoneInfo("America/Sao_Paulo")) - timedelta(days=1)
        repeated = item("Frank Aguiar chora morte do pai e desabafa nas redes").model_copy(update={"published_at": yesterday})
        other = item("Marisa Monte anuncia turnê nova").model_copy(update={"published_at": yesterday})
        store = mock.Mock()
        store.is_seen.return_value = False
        store.recent_short_titles.return_value = ["Frank Aguiar chora ao anunciar morte do pai nas redes"]
        with mock.patch("src.pipeline._select_with_classic_fallback", return_value=([], False)) as select:
            pipeline._yesterday_fallback_items([repeated, other], store, 1)
        self.assertEqual([candidate.title for candidate in select.call_args.args[0]], [other.title])

    def test_experiment_failure_falls_back_to_short_script(self):
        from src import pipeline

        with mock.patch("src.pipeline.script_arm", side_effect=RuntimeError("boom")):
            self.assertEqual(pipeline._script_arm(mock.Mock()), experiment.ARM_SHORT)


if __name__ == "__main__":
    unittest.main()
