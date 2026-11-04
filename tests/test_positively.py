"""Tests for the positively positive-framing engine."""

import tempfile
import unittest
from pathlib import Path

from positively import engine, patterns, config


class FramingTest(unittest.TestCase):
    def setUp(self):
        cfg = config.Config(root=Path(tempfile.gettempdir()))
        engine.set_config(cfg)

    def test_phrase_reversal(self):
        text, _ = engine.reverse_framing("This is a hard gate.")
        self.assertIn("milestone", text)
        self.assertNotIn("hard gate", text)

    def test_word_reversal(self):
        text, _ = engine.reverse_framing("The operation refused.")
        self.assertIn("declined", text)
        self.assertNotIn("refused", text)

    def test_idempotent(self):
        src = "hard gate, refused, blocked, unrecoverable, do not"
        once, _ = engine.reverse_framing(src)
        twice, _ = engine.reverse_framing(once)
        self.assertEqual(once, twice)

    def test_negations_not_inverted(self):
        for src in [
            "only calls the saved pointer (never the global)",
            "do not edit by hand — regenerate with build script",
            "the cache-hit path cannot hide a compile",
            "one bad file never kills the batch",
        ]:
            out, _ = engine.reverse_framing(src)
            self.assertEqual(out, src, f"negation inverted in: {src!r}")

    def test_excludes_configured_identifiers(self):
        cfg = config.Config(root=Path(tempfile.gettempdir()))
        cfg.identifier_exclusions = {"SCOPE_GATED"}
        engine.set_config(cfg)
        src = "SCOPE_GATED should not be changed"
        out, _ = engine.reverse_framing(src)
        self.assertIn("SCOPE_GATED", out)

    def test_technical_term_preserved(self):
        cfg = config.Config(root=Path(tempfile.gettempdir()))
        cfg.technical_terms = {"never_type"}
        engine.set_config(cfg)
        src = "never_type is a keyword"
        out, _ = engine.reverse_framing(src)
        self.assertEqual(out, src)

    def test_string_literal_exclusion(self):
        cfg = config.Config(root=Path(tempfile.gettempdir()))
        cfg.string_exclusions = {"halt"}
        engine.set_config(cfg)
        src = 'the JSON value "halt" stays'
        out, _ = engine.reverse_framing(src)
        self.assertIn('"halt"', out)


class ConfigOverrideTest(unittest.TestCase):
    def test_custom_exclusions(self):
        cfg = config.Config(root=Path(tempfile.gettempdir()))
        cfg.identifier_exclusions = {"BLOCKED", "HALT", "LOCKED"}
        cfg.string_exclusions = {"halt"}
        engine.set_config(cfg)
        out, _ = engine.reverse_framing("BLOCKED and halt and 'halt'")
        self.assertIn("BLOCKED", out)
        self.assertIn("halt", out)

    def test_custom_phrases(self):
        cfg = config.Config(root=Path(tempfile.gettempdir()))
        cfg.phrase_map = [("hard gate", "milestone")]
        engine.set_config(cfg)
        text, _ = engine.reverse_framing("hard gate")
        self.assertIn("milestone", text)


class BlockerTest(unittest.TestCase):
    def setUp(self):
        cfg = config.Config(root=Path(tempfile.gettempdir()))
        import re
        cfg.blocker_patterns = [
            (re.compile(r"return\s+BLOCKED"), "blocked-return", "high", "Route to permissive default"),
            (re.compile(r"raise\s+BlockException"), "block-exception", "high", "Replace with passthrough"),
        ]
        engine.set_config(cfg)

    def test_detect_configured_blocker(self):
        rep = engine.scan_blockers(Path("x.py"), "return BLOCKED for this path")
        self.assertTrue(rep)
        self.assertEqual(rep[0].severity, "high")

    def test_no_false_blocker(self):
        rep = engine.scan_blockers(Path("x.py"), "def blocked():\n    pass")
        self.assertFalse(rep)


class ApplyTest(unittest.TestCase):
    def setUp(self):
        cfg = config.Config(root=Path(tempfile.gettempdir()))
        engine.set_config(cfg)

    def test_apply_framing_markdown(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "x.md"
            p.write_text("hard gate and refused")
            out, n = engine.apply_framing(p, p.read_text())
            self.assertIn("milestone", out)
            self.assertGreater(n, 0)

    def test_apply_keeps_inline_code(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.md"
            p.write_text("The run refused `body not recovered` here.\n")
            out, _ = engine.apply_framing(p, p.read_text())
            self.assertIn("`body not recovered`", out)
            self.assertNotIn("refused", out)

    def test_scan_ignores_inline_code(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.md"
            p.write_text("Quoted: `method body not recovered`.\n")
            rep = engine.scan_path(p)
            self.assertEqual(rep.framing, [])
            p.write_text("The body was not recovered.\n")
            self.assertTrue(engine.scan_path(p).framing)

    def test_apply_skips_code_block(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "x.md"
            p.write_text("```\nSCOPE_GATED\n```\nrefused")
            out, _ = engine.apply_framing(p, p.read_text())
            self.assertIn("SCOPE_GATED", out)
            self.assertIn("declined", out)

    def test_apply_source_comments(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.py"
            p.write_text("# This is a hard gate\nx = 1  # refused by gate\n")
            out, n = engine.apply_framing(p, p.read_text())
            self.assertIn("milestone", out)
            self.assertIn("declined", out)
            self.assertGreater(n, 0)


class AuditLogTest(unittest.TestCase):
    def test_no_entries_writes_nothing(self):
        from positively.apply import _log_audit
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "audit.md"
            self.assertFalse(_log_audit([], log_path=log))
            self.assertFalse(log.exists())

    def test_entries_append_one_section(self):
        from positively.apply import _log_audit
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "audit.md"
            self.assertTrue(_log_audit(["a.md: framing x1"], log_path=log))
            text = log.read_text()
            self.assertEqual(text.count("\n## "), 1)
            self.assertIn("- a.md: framing x1\n", text)


class MapValidationTest(unittest.TestCase):
    """Regression guard for the 7.60-class bug: output words must never re-enter
    the negative set, and no map may touch a protected term or map to itself."""

    def test_no_output_is_also_negative(self):
        problems = patterns.validate_maps(patterns.PHRASE_MAP, patterns.WORD_MAP)
        self.assertEqual(problems, [], f"map has contradictions: {problems}")

    def test_self_map_rejected(self):
        problems = patterns.validate_maps([("foo", "foo")], {})
        self.assertTrue(any("itself" in p for p in problems))

    def test_protected_term_negative_rejected(self):
        problems = patterns.validate_maps([("illegal", "acceptable")], {})
        self.assertTrue(any("illegal" in p for p in problems))

    def test_protected_term_output_rejected(self):
        problems = patterns.validate_maps([("fine", "illegal")], {})
        self.assertTrue(any("illegal" in p for p in problems))


class ProtectedTermTest(unittest.TestCase):
    def setUp(self):
        self.cfg = config.Config(root=Path(tempfile.gettempdir()))
        engine.set_config(self.cfg)

    def test_legal_term_never_rewritten(self):
        out, changes = engine.reverse_framing("this is illegal and prohibited")
        self.assertIn("illegal", out)
        self.assertIn("prohibited", out)
        self.assertEqual(changes, [])

    def test_secret_term_never_rewritten(self):
        out, _ = engine.reverse_framing("the password is a secret")
        self.assertIn("password", out)
        self.assertIn("secret", out)

    def test_config_cannot_override_protected_term(self):
        cfg = config.Config(root=Path(tempfile.gettempdir()))
        cfg.phrase_map = list(patterns.PHRASE_MAP) + [("illegal", "acceptable")]
        engine.set_config(cfg)
        out, _ = engine.reverse_framing("this is illegal")
        self.assertIn("illegal", out)
        self.assertNotIn("acceptable", out)


class CautionTest(unittest.TestCase):
    def setUp(self):
        self.cfg = config.Config(root=Path(tempfile.gettempdir()))
        engine.set_config(self.cfg)

    def _scan(self, text):
        return engine.scan_cautions(Path("x.sh"), text)

    def test_detect_rm_rf(self):
        rep = self._scan("rm -rf /tmp/build")
        self.assertTrue(rep)
        self.assertEqual(rep[0].label, "destructive-remove")

    def test_detect_force_push(self):
        rep = self._scan("git push --force origin main")
        self.assertTrue(any("force-push" == r.label for r in rep))

    def test_detect_hard_reset(self):
        rep = self._scan("git reset --hard HEAD~1")
        self.assertTrue(any("hard-reset" == r.label for r in rep))

    def test_detect_drop_table(self):
        rep = self._scan("DROP TABLE users")
        self.assertTrue(any("drop-table" == r.label for r in rep))

    def test_detect_delete_from(self):
        rep = self._scan("DELETE FROM customers WHERE id = 1")
        self.assertTrue(any("delete-from" == r.label for r in rep))

    def test_no_false_positive_on_archive(self):
        rep = self._scan("git archive --format=tar HEAD")
        self.assertFalse(rep)


class NewExtensionTest(unittest.TestCase):
    def setUp(self):
        self.cfg = config.Config(root=Path(tempfile.gettempdir()))
        engine.set_config(self.cfg)

    def test_yaml_comment_rewritten(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.yaml"
            p.write_text("# This is a hard gate\nkey: value\n")
            out, n = engine.apply_framing(p, p.read_text())
            self.assertIn("milestone", out)
            self.assertGreater(n, 0)

    def test_html_comment_rewritten(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "index.html"
            p.write_text("<!-- refused by the gate -->\n")
            out, n = engine.apply_framing(p, p.read_text())
            self.assertIn("declined", out)

    def test_makefile_comment_rewritten(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "Makefile"
            p.write_text("# this is a hard gate\nall:\n\t@echo hi\n")
            out, n = engine.apply_framing(p, p.read_text())
            self.assertIn("milestone", out)

    def test_full_map_idempotent(self):
        sample = " ".join(neg for neg, _ in patterns.PHRASE_MAP) + " " + " ".join(patterns.WORD_MAP)
        once, _ = engine.reverse_framing(sample)
        twice, _ = engine.reverse_framing(once)
        self.assertEqual(once, twice)


if __name__ == "__main__":
    unittest.main()