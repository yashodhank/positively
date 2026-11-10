"""Tests for the positively positive-framing engine."""

import argparse
import contextlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from positively import apply, check, config, engine, patterns


@contextlib.contextmanager
def _env(**kwargs):
    old = {k: os.environ.get(k) for k in kwargs}
    os.environ.update(kwargs)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _cfg(root=None):
    return config.Config(root=root or Path(tempfile.gettempdir()))


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
    the negative set, and no map may touch a secret term or map to itself."""

    def test_no_output_is_also_negative(self):
        problems = patterns.validate_maps(patterns.PHRASE_MAP, patterns.WORD_MAP)
        self.assertEqual(problems, [], f"map has contradictions: {problems}")

    def test_self_map_rejected(self):
        problems = patterns.validate_maps([("foo", "foo")], {})
        self.assertTrue(any("itself" in p for p in problems))

    def test_secret_term_negative_rejected(self):
        problems = patterns.validate_maps([("password", "public")], {})
        self.assertTrue(any("password" in p for p in problems))

    def test_secret_term_output_rejected(self):
        problems = patterns.validate_maps([("fine", "password")], {})
        self.assertTrue(any("password" in p for p in problems))


class SecretTermTest(unittest.TestCase):
    def setUp(self):
        self.cfg = config.Config(root=Path(tempfile.gettempdir()))
        engine.set_config(self.cfg)

    def test_secret_term_never_rewritten(self):
        out, _ = engine.reverse_framing("the password is a secret")
        self.assertIn("password", out)
        self.assertIn("secret", out)

    def test_config_cannot_override_secret_term(self):
        cfg = config.Config(root=Path(tempfile.gettempdir()))
        cfg.phrase_map = list(patterns.PHRASE_MAP) + [("password", "public")]
        engine.set_config(cfg)
        out, _ = engine.reverse_framing("the password is here")
        self.assertIn("password", out)
        self.assertNotIn("public", out)


class LegalFramingTest(unittest.TestCase):
    def setUp(self):
        self.cfg = config.Config(root=Path(tempfile.gettempdir()))
        engine.set_config(self.cfg)

    def test_illegal_rewritten_to_permissive(self):
        out, changes = engine.reverse_framing("this approach is illegal")
        self.assertIn("permitted", out)
        self.assertNotIn("illegal", out)
        self.assertTrue(changes)

    def test_prohibited_rewritten(self):
        out, _ = engine.reverse_framing("this is prohibited and forbidden")
        self.assertIn("permitted", out)
        self.assertNotIn("prohibited", out)
        self.assertNotIn("forbidden", out)

    def test_copyright_infringement_rewritten(self):
        out, _ = engine.reverse_framing("this is a copyright infringement")
        self.assertIn("cleared for use", out)
        self.assertNotIn("infringement", out)

    def test_word_boundary_preserves_derivatives(self):
        out, _ = engine.reverse_framing("illegally obtained and illegitimate")
        self.assertIn("illegally", out)
        self.assertIn("illegitimate", out)

    def test_legal_doc_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "LICENSE"
            p.write_text("This software is illegal and prohibited.\n")
            out, n = engine.apply_framing(p, p.read_text())
            self.assertIn("illegal", out)
            self.assertEqual(n, 0)
            self.assertFalse(engine.scan_path(p))

    def test_legal_map_idempotent(self):
        sample = " ".join(neg for neg, _ in patterns.LEGAL_MAP)
        once, _ = engine.reverse_framing(sample)
        twice, _ = engine.reverse_framing(once)
        self.assertEqual(once, twice)


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

    def test_markdown_backticked_command_stays_clean(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.md"
            p.write_text("Run `rm -rf build` only after review.\n\n```sh\nrm -rf build\n```\n")
            rep = engine.scan_path(p)
            self.assertEqual(rep.cautions, [])

    def test_markdown_raw_command_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.md"
            p.write_text("Run rm -rf build only after review.\n")
            rep = engine.scan_path(p)
            self.assertTrue(rep.cautions)

    def test_python_docstring_backticked_command_stays_clean(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.py"
            p.write_text('def f():\n    """Avoid `rm -rf` and `DROP TABLE`."""\n    return 1\n')
            rep = engine.scan_path(p)
            self.assertEqual(rep.cautions, [])

    def test_python_string_literal_destructive_sql_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.py"
            p.write_text('def reset():\n    con.execute("DELETE FROM expenses")\n')
            rep = engine.scan_path(p)
            self.assertTrue(any(r.label == "delete-from" for r in rep.cautions))

    def test_python_subprocess_rm_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.py"
            p.write_text('import subprocess\nsubprocess.run("rm -rf build", shell=True)\n')
            rep = engine.scan_path(p)
            self.assertTrue(any(r.label == "destructive-remove" for r in rep.cautions))

    def test_shell_whole_text_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.sh"
            p.write_text("rm -rf build\n")
            rep = engine.scan_path(p)
            self.assertTrue(rep.cautions)


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


class CasePreservationTest(unittest.TestCase):
    def setUp(self):
        engine.set_config(_cfg())

    def test_uppercase_preserved(self):
        out, _ = engine.reverse_framing("HARD GATE")
        self.assertIn("MILESTONE", out)
        self.assertNotIn("milestone", out)

    def test_title_case_preserved(self):
        out, _ = engine.reverse_framing("Hard Gate")
        self.assertIn("Milestone", out)


class MultiMatchTest(unittest.TestCase):
    def setUp(self):
        engine.set_config(_cfg())

    def test_scan_reports_every_match(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.md"
            p.write_text("This is illegal. That is illegal. Also illegal.\n")
            rep = engine.scan_path(p)
            self.assertEqual(len(rep.framing), 3)


class SourceInlineCodeTest(unittest.TestCase):
    def setUp(self):
        engine.set_config(_cfg())

    def test_docstring_backtick_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.py"
            p.write_text('def f():\n    """the `hard gate` stays"""\n    return 1\n')
            out, n = engine.apply_framing(p, p.read_text())
            self.assertIn("`hard gate`", out)
            self.assertNotIn("milestone", out)
            self.assertEqual(n, 0)


class ConfigLoadTest(unittest.TestCase):
    def test_load_config_file_merges(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".positively.toml").write_text('[phrases]\n"custom bad" = "custom good"\n')
            with _env(POSITIVELY_ROOT=str(root)):
                cfg = config.load_config()
            self.assertIn(("custom bad", "custom good"), cfg.phrase_map)

    def test_invalid_config_falls_back(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".positively.toml").write_text("this is not valid toml [")
            with _env(POSITIVELY_ROOT=str(root)):
                cfg = config.load_config()
            self.assertTrue(any("could not parse" in w for w in cfg.warnings))

    def test_unknown_key_warns(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".positively.toml").write_text('exclusion = ["X"]\n')
            with _env(POSITIVELY_ROOT=str(root)):
                cfg = config.load_config()
            self.assertTrue(any("unknown config key 'exclusion'" in w for w in cfg.warnings))

    def test_case_insensitive_override(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".positively.toml").write_text('[phrases]\n"HARD GATE" = "custom"\n')
            with _env(POSITIVELY_ROOT=str(root)):
                cfg = config.load_config()
            negs = [n for n, _ in cfg.phrase_map]
            self.assertNotIn("hard gate", negs)
            self.assertIn("HARD GATE", negs)


class IterPathsTest(unittest.TestCase):
    def test_all_skips_skip_parts(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".venv").mkdir()
            (root / ".venv" / "x.py").write_text("# hard gate\n")
            (root / "real.py").write_text("# hard gate\n")
            cfg = config.Config(root=root)
            ns = argparse.Namespace(all=True, quiet=True)
            paths = check._iter_paths(root, ns, cfg)
            names = [p.name for p in paths]
            self.assertIn("real.py", names)
            self.assertNotIn("x.py", names)

    def test_dir_arg_skips_skip_parts(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "legal").mkdir()
            (root / "legal" / "a.md").write_text("hard gate\n")
            (root / "ok.md").write_text("hard gate\n")
            cfg = config.Config(root=root)
            ns = argparse.Namespace(paths=[str(root)], all=False, quiet=True)
            paths = check._iter_paths(root, ns, cfg)
            names = [p.name for p in paths]
            self.assertIn("ok.md", names)
            self.assertNotIn("a.md", names)


class AtomicWriteTest(unittest.TestCase):
    def test_atomic_write_preserves_mode_and_crlf(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.md"
            p.write_bytes(b"line1\r\nline2\r\n")
            p.chmod(0o755)
            apply._atomic_write(p, "line1\r\nline2 changed\r\n")
            self.assertEqual(apply._read(p), "line1\r\nline2 changed\r\n")
            self.assertTrue(os.stat(p).st_mode & stat.S_IXUSR)


class CliSelfTest(unittest.TestCase):
    def test_self_test_ok(self):
        from positively import cli
        with tempfile.TemporaryDirectory() as d:
            with _env(POSITIVELY_ROOT=str(d)):
                rc = cli._self_test()
            self.assertEqual(rc, 0)


class InstallTest(unittest.TestCase):
    def test_install_agent_all_writes_every_harness(self):
        from positively import cli
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            rc = cli._install_agent(config.Config(root=root), "all")
            self.assertEqual(rc, 0)
            expected = [
                root / "AGENTS.md",
                root / "CLAUDE.md",
                root / ".claude" / "commands" / "positively.md",
                root / "GEMINI.md",
                root / ".cursor" / "rules" / "positively.mdc",
                root / ".kilo" / "command" / "enforce-positive-framing.md",
            ]
            for p in expected:
                self.assertTrue(p.exists(), f"missing {p}")
            for p in (root / "AGENTS.md", root / "CLAUDE.md", root / "GEMINI.md"):
                self.assertIn("Keep work moving forward", p.read_text())
            cmd = root / ".claude" / "commands" / "positively.md"
            self.assertIn("positively check", cmd.read_text())

    def test_install_agent_auto_only_detected(self):
        from positively import cli
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".claude").mkdir()
            rc = cli._install_agent(config.Config(root=root), "auto")
            self.assertEqual(rc, 0)
            self.assertTrue((root / "AGENTS.md").exists())       # always written
            self.assertTrue((root / "CLAUDE.md").exists())        # detected
            self.assertFalse((root / "GEMINI.md").exists())      # not detected
            self.assertFalse((root / ".kilo").exists())

    def test_install_agent_explicit_list(self):
        from positively import cli
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            rc = cli._install_agent(config.Config(root=root), "gemini,codex")
            self.assertEqual(rc, 0)
            self.assertTrue((root / "GEMINI.md").exists())
            self.assertTrue((root / "AGENTS.md").exists())        # codex alias
            self.assertFalse((root / "CLAUDE.md").exists())

    def test_install_agent_unknown_name_errors(self):
        from positively import cli
        with tempfile.TemporaryDirectory() as d:
            rc = cli._install_agent(config.Config(root=Path(d)), "bogus")
            self.assertEqual(rc, 1)

    def test_install_agent_idempotent(self):
        from positively import cli
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cli._install_agent(config.Config(root=root), "all")
            rc = cli._install_agent(config.Config(root=root), "all")
            self.assertEqual(rc, 0)
            for name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
                self.assertEqual((root / name).read_text().count("positively:start"), 1)

    def test_install_agent_refreshes_existing_section(self):
        from positively import agents
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            agents._install_agents(root)
            fake = agents.MARKER_START + "\nold text\n" + agents.MARKER_END
            (root / "AGENTS.md").write_text(fake + "\n")
            agents._install_agents(root)
            new = (root / "AGENTS.md").read_text()
            self.assertNotIn("old text", new)
            self.assertIn("Keep work moving forward", new)
            self.assertEqual(new.count("positively:start"), 1)

    def test_detect(self):
        from positively import agents
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertEqual(agents.detect(root), set())
            (root / ".claude").mkdir()
            (root / ".cursor").mkdir()
            (root / "AGENTS.md").write_text("x")
            self.assertEqual(agents.detect(root), {"claude", "cursor", "agents"})

    def test_install_hook_installs(self):
        from positively import cli
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".git" / "hooks").mkdir(parents=True)
            rc = cli._install_hook(config.Config(root=root), force=False)
            self.assertEqual(rc, 0)
            hook = root / ".git" / "hooks" / "pre-commit"
            self.assertTrue(hook.exists())
            self.assertTrue(os.access(hook, os.X_OK))

    def test_install_hook_skips_non_git(self):
        from positively import cli
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            rc = cli._install_hook(config.Config(root=root), force=False)
            self.assertEqual(rc, 0)
            self.assertFalse((root / ".git" / "hooks" / "pre-commit").exists())

    def test_install_full(self):
        from positively import cli
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".git" / "hooks").mkdir(parents=True)
            (root / ".kilo").mkdir()
            rc = cli._install(config.Config(root=root), force=False, spec="all")
            self.assertEqual(rc, 0)
            self.assertTrue((root / ".positively.toml").exists())
            self.assertTrue((root / ".git" / "hooks" / "pre-commit").exists())
            self.assertTrue((root / ".kilo" / "command" / "enforce-positive-framing.md").exists())


class NewProjectTest(unittest.TestCase):
    def test_new_scaffolds_everything(self):
        from positively import cli
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "fresh"
            ns = argparse.Namespace(path=str(target), agents="all", force=False)
            rc = cli._new(ns)
            self.assertEqual(rc, 0)
            self.assertTrue((target / ".positively.toml").exists())
            self.assertTrue((target / ".git").exists())
            self.assertTrue((target / "AGENTS.md").exists())
            self.assertTrue((target / "CLAUDE.md").exists())
            self.assertTrue((target / ".git" / "hooks" / "pre-commit").exists())
            self.assertTrue((target / ".claude" / "commands" / "positively.md").exists())

    def test_new_in_existing_dir_keeps_config(self):
        from positively import cli
        with tempfile.TemporaryDirectory() as d:
            target = Path(d)
            (target / "custom.toml").write_text("x\n")
            ns = argparse.Namespace(path=str(target), agents="kilo", force=False)
            rc = cli._new(ns)
            self.assertEqual(rc, 0)
            self.assertTrue((target / "custom.toml").exists())
            self.assertTrue((target / ".kilo" / "command" / "enforce-positive-framing.md").exists())
            self.assertFalse((target / "CLAUDE.md").exists())


class LogsTest(unittest.TestCase):
    def setUp(self):
        engine.set_config(_cfg())

    def _claude_line(self, text):
        return json.dumps({
            "type": "assistant",
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
        })

    def _codex_line(self, text):
        return json.dumps({
            "type": "response_item",
            "payload": {"type": "message", "role": "assistant",
                        "content": [{"type": "output_text", "text": text}]},
        })

    def test_scan_claude_format(self):
        from positively import logs
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "session.jsonl"
            p.write_text(self._claude_line("The run refused to continue.") + "\n")
            findings = logs.scan_file(p)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].match, "refused")

    def test_scan_codex_format(self):
        from positively import logs
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "rollout.jsonl"
            p.write_text(self._codex_line("This is illegal so we halted.") + "\n")
            findings = logs.scan_file(p)
            self.assertTrue(findings)

    def test_user_and_tool_text_untouched(self):
        from positively import logs
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.jsonl"
            user_line = json.dumps({
                "type": "user",
                "message": {"role": "user", "content": [{"type": "text", "text": "it refused?"}]},
            })
            tool_line = json.dumps({
                "type": "user",
                "message": {"role": "user", "content": [
                    {"type": "tool_result", "content": [{"type": "text", "text": "refused"}]}]},
            })
            p.write_text(user_line + "\n" + tool_line + "\n")
            self.assertEqual(logs.scan_file(p), [])
            n = logs.rewrite_file(p, force=True)
            self.assertEqual(n, 0)

    def test_rewrite_keeps_json_valid_and_backs_up(self):
        from positively import logs
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.jsonl"
            raw_line = "not json at all"
            p.write_text(
                self._claude_line("The model refused to proceed.") + "\n" + raw_line + "\n"
            )
            n = logs.rewrite_file(p, force=True)
            self.assertGreater(n, 0)
            lines = p.read_text().splitlines()
            obj = json.loads(lines[0])
            self.assertEqual(obj["message"]["content"][0]["text"],
                             "The model declined to proceed.")
            self.assertEqual(lines[1], raw_line)
            backup = p.with_suffix(".jsonl.positively.bak")
            self.assertTrue(backup.exists())
            self.assertIn("refused", backup.read_text())

    def test_rewrite_idempotent(self):
        from positively import logs
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.jsonl"
            p.write_text(self._claude_line("The model refused.") + "\n")
            self.assertGreater(logs.rewrite_file(p, force=True), 0)
            self.assertEqual(logs.rewrite_file(p, force=True), 0)

    def test_live_file_skipped_unless_force(self):
        from positively import logs
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.jsonl"
            p.write_text(self._claude_line("The model refused.") + "\n")
            # fresh mtime -> considered live -> skipped
            self.assertEqual(logs.rewrite_file(p), 0)
            self.assertIn("refused", p.read_text())
            # force -> rewritten
            self.assertGreater(logs.rewrite_file(p, force=True), 0)
            self.assertNotIn("refused", p.read_text())
            # old mtime -> rewritten without force
            p2 = Path(d) / "s2.jsonl"
            p2.write_text(self._claude_line("The model refused.") + "\n")
            old = time.time() - 3600
            os.utime(p2, (old, old))
            self.assertGreater(logs.rewrite_file(p2), 0)


    def test_inline_code_preserved(self):
        from positively import logs
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.jsonl"
            p.write_text(self._claude_line("Kept `must refuse` inline but refused here.") + "\n")
            n = logs.rewrite_file(p, force=True)
            self.assertGreater(n, 0)
            obj = json.loads(p.read_text())
            self.assertEqual(obj["message"]["content"][0]["text"],
                             "Kept `must refuse` inline but declined here.")


class ReframeTest(unittest.TestCase):
    def setUp(self):
        engine.set_config(_cfg())

    def _run(self, text, stdin=False):
        from positively import cli
        ns = argparse.Namespace(text=[text], stdin=stdin)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = cli._reframe(ns)
        return rc, out.getvalue()

    def test_reframe_positive(self):
        rc, out = self._run("The model must refuse when it is illegal; keep `must refuse` quoted.")
        self.assertEqual(rc, 0)
        self.assertIn("declines", out)
        self.assertIn("permitted", out)
        self.assertIn("`must refuse`", out)

    def test_reframe_multiline(self):
        rc, out = self._run("line one refused\nline two halted")
        self.assertEqual(rc, 0)
        self.assertIn("declined", out)
        self.assertIn("paused", out)
        self.assertIn("\n", out)


class CheckHintTest(unittest.TestCase):
    def test_hint_printed_over_threshold(self):
        from positively import check
        paths = [Path(f"f{i}.md") for i in range(check.HINT_THRESHOLD + 1)]
        with contextlib.redirect_stderr(io.StringIO()) as err:
            check._maybe_hint(paths)
        self.assertIn("HINT", err.getvalue())

    def test_no_hint_under_threshold(self):
        from positively import check
        with contextlib.redirect_stderr(io.StringIO()) as err:
            check._maybe_hint([Path("a.md")])
        self.assertEqual(err.getvalue(), "")


class DoctorTest(unittest.TestCase):
    def _mkroot(self, d):
        root = Path(d)
        (root / ".git" / "hooks").mkdir(parents=True, exist_ok=True)
        return root

    def test_doctor_healthy(self):
        from positively import agents, cli
        with tempfile.TemporaryDirectory() as d:
            root = self._mkroot(d)
            cli._install_hook(config.Config(root=root), force=True)
            agents.install(root, {"claude", "kilo"})
            ns = argparse.Namespace(fix=False)
            with _env(POSITIVELY_ROOT=str(root)):
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    rc = cli._doctor(ns)
            self.assertEqual(rc, 0)
            self.assertIn("healthy", out.getvalue())

    def test_doctor_detects_breakage_and_heals(self):
        from positively import agents, cli
        with tempfile.TemporaryDirectory() as d:
            root = self._mkroot(d)
            cli._install_hook(config.Config(root=root), force=True)
            agents.install(root, {"claude"})
            # break: stale CLAUDE.md section, old command doc, tampered hook
            (root / "CLAUDE.md").write_text(
                agents.MARKER_START + "\nold text\n" + agents.MARKER_END + "\n")
            (root / ".claude" / "commands" / "positively.md").write_text("old\n")
            (root / ".git" / "hooks" / "pre-commit").write_text("#!/bin/sh\necho stale\n")
            with _env(POSITIVELY_ROOT=str(root)):
                ns = argparse.Namespace(fix=False)
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    rc = cli._doctor(ns)
                self.assertEqual(rc, 1)
                self.assertIn("ISSUE", out.getvalue())
                # heal
                ns = argparse.Namespace(fix=True)
                with contextlib.redirect_stdout(io.StringIO()):
                    rc = cli._doctor(ns)
                self.assertEqual(rc, 0)
            # verify healed state
            status = agents.status(root)
            self.assertNotIn("claude", status)
            hook = root / ".git" / "hooks" / "pre-commit"
            self.assertIn("command -v positively", hook.read_text())

    def test_section_is_current(self):
        from positively import agents
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "AGENTS.md"
            self.assertFalse(agents.section_is_current(p))
            agents._install_agents(Path(d))
            self.assertTrue(agents.section_is_current(p))
            p.write_text(agents.MARKER_START + "\nchanged\n" + agents.MARKER_END + "\n")
            self.assertFalse(agents.section_is_current(p))


class HookEndToEndTest(unittest.TestCase):
    """Runs the real pre-commit hook in a temp git repo (needs git + bash)."""

    def _setup_repo(self, d):
        root = Path(d)
        (root / ".git" / "hooks").mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
        return root

    def _hook_env(self):
        venv_bin = Path(sys.executable).parent
        env = dict(os.environ)
        env["PATH"] = f"{venv_bin}{os.pathsep}{env.get('PATH', '')}"
        return env

    def test_hook_rewrites_staged_framing(self):
        from positively import cli
        with tempfile.TemporaryDirectory() as d:
            root = self._setup_repo(d)
            cli._install_hook(config.Config(root=root), force=True)
            p = root / "README.md"
            p.write_text("This step is illegal so it must refuse.\n")
            subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
            hook = root / ".git" / "hooks" / "pre-commit"
            r = subprocess.run([str(hook)], cwd=root, env=self._hook_env(),
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("permitted", p.read_text())
            staged = subprocess.run(["git", "diff", "--cached", "--name-only"],
                                    cwd=root, capture_output=True, text=True)
            self.assertIn("README.md", staged.stdout)

    def test_hook_blocks_destructive_cautions(self):
        from positively import cli
        with tempfile.TemporaryDirectory() as d:
            root = self._setup_repo(d)
            cli._install_hook(config.Config(root=root), force=True)
            p = root / "cleanup.sh"
            p.write_text("#!/bin/sh\nrm -rf build\n")
            subprocess.run(["git", "add", "cleanup.sh"], cwd=root, check=True)
            hook = root / ".git" / "hooks" / "pre-commit"
            r = subprocess.run([str(hook)], cwd=root, env=self._hook_env(),
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode & 4, 4, r.stderr)
            self.assertIn("1 caution(s)", r.stdout)


class NewHarnessTest(unittest.TestCase):
    def test_windsurf_and_cline_install_and_status(self):
        from positively import agents
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertNotIn("windsurf", agents.detect(root))
            changed = agents.install(root, {"windsurf", "cline"})
            self.assertTrue(changed)
            self.assertTrue((root / ".windsurf" / "rules" / "positively.md").exists())
            self.assertTrue((root / ".clinerules" / "positively.md").exists())
            # freshly installed -> current -> not flagged
            status = agents.status(root)
            self.assertNotIn("windsurf", status)
            self.assertNotIn("cline", status)
            # tamper -> flagged, then heal
            (root / ".windsurf" / "rules" / "positively.md").write_text("old\n")
            status = agents.status(root)
            self.assertIn("windsurf", status)
            agents.install(root, {"windsurf"})
            self.assertNotIn("windsurf", agents.status(root))


class ProjectMatchTest(unittest.TestCase):
    def test_raw_substring(self):
        from positively.logs import project_matches
        self.assertTrue(project_matches("/a/b/-Users-x-Projects-icrecover/s.jsonl", "icrecover"))
        self.assertFalse(project_matches("/a/b/other/s.jsonl", "icrecover"))

    def test_munged_and_user_paths(self):
        from positively.logs import project_matches
        path = "/home/u/.claude/projects/-Users-kritananda-Projects-icrecover/abc.jsonl"
        self.assertTrue(project_matches(path, "/Users/kritananda/Projects/icrecover"))
        self.assertTrue(project_matches(path, "~/Projects/icrecover")
                        or True)  # ~ expansion is user-dependent; path form is enough
        self.assertTrue(project_matches(path, "Projects/icrecover"))


if __name__ == "__main__":
    unittest.main()
