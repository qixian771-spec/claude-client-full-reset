import contextlib
import io
import json
from pathlib import Path
import sys
import unittest

import yaml
from unittest.mock import patch

from test_workflows import Fixture, ROOT, BS, SQL, common, platforms, make_db
import telemetry_routing as TR


class DomainExpansionTests(Fixture):
    def test_expanded_first_party_domains_match_sqlite_and_firefox(self):
        db = self.home / 'History'
        make_db(db, [
            ('https://claude.ai/chat', 'main'),
            ('https://claude.com/login', 'login redirect'),
            ('https://clau.de/short', 'short link'),
            ('https://code.claude.com/docs/en/network-config', 'docs'),
            ('https://api.anthropic.com/v1/messages', 'api'),
            ('https://assets-proxy.anthropic.com/bundle.js', 'cdn'),
            ('https://bridge.claudeusercontent.com/chrome/1', 'bridge'),
            ('https://abc.frame.claudeusercontent.com/index.html', 'artifact'),
            ('https://rpc.claudemcpclient.com/connect', 'mcp client'),
            ('https://widget.claudemcpcontent.com/app.js', 'mcp widget'),
            ('https://example.com/unrelated', 'keep'),
        ])
        count, _ = SQL.purge_db(db)
        self.assertEqual(count, 10)
        for origin, expected in (
            ('https+++claude.com', True),
            ('https+++clau.de', True),
            ('https+++code.claude.com^userContextId=1', True),
            ('https+++bridge.claudeusercontent.com', True),
            ('https+++x.claudemcpclient.com', True),
            ('https+++x.claudemcpcontent.com', True),
            ('https+++notclaude.com', False),
        ):
            with self.subTest(origin=origin):
                self.assertEqual(BS.firefox_origin_matches(origin), expected)


class TelemetryRoutingTests(Fixture):
    def test_readonly_detects_missing_settings_and_rules_without_writing(self):
        report = TR.collect(home=self.home, proxy_group='ClaudeProxy')
        self.assertTrue(report['has_gaps'])
        self.assertFalse(report['settings']['exists'])
        self.assertEqual(len(report['settings']['missing_keys']), len(TR.TELEMETRY_ENV_SPEC))
        self.assertGreater(report['routing']['missing_rules_count'], 40)
        self.assertIn('timezone_check', report)
        self.assertFalse((self.home / '.claude/settings.json').exists())

    def test_apply_preserves_existing_settings_and_only_supplements_missing(self):
        settings_path = self.file('.claude/settings.json', json.dumps({
            'permissions': {'allow': ['Read']},
            'env': {
                'ANTHROPIC_BASE_URL': 'https://gateway.internal.example',
                'ANTHROPIC_AUTH_TOKEN': 'sk-secret-do-not-print',
                'DISABLE_TELEMETRY': 'custom-keep',
            },
        }))
        out_dir = self.root / 'routing-out'
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            result = TR.apply_all(home=self.home, proxy_group='MyProxy', out_dir=out_dir)
            TR.print_human_report(TR.collect(home=self.home, proxy_group='MyProxy'))
        output_text = stdout.getvalue()
        self.assertNotIn('sk-secret-do-not-print', output_text)
        self.assertNotIn('gateway.internal.example', output_text)
        self.assertTrue(result['settings_update']['changed'])
        self.assertIn('DISABLE_TELEMETRY', result['settings_update']['kept_keys'])
        self.assertNotIn('DISABLE_TELEMETRY', result['settings_update']['added_keys'])
        self.assertTrue(Path(result['settings_update']['backup']).is_file())

        updated = json.loads(settings_path.read_text(encoding='utf-8'))
        self.assertEqual(updated['permissions'], {'allow': ['Read']})
        self.assertEqual(updated['env']['ANTHROPIC_BASE_URL'], 'https://gateway.internal.example')
        self.assertEqual(updated['env']['ANTHROPIC_AUTH_TOKEN'], 'sk-secret-do-not-print')
        # Existing key was NOT overwritten:
        self.assertEqual(updated['env']['DISABLE_TELEMETRY'], 'custom-keep')
        # Missing keys were supplemented:
        self.assertEqual(updated['env']['DISABLE_ERROR_REPORTING'], '1')
        self.assertEqual(updated['env']['DO_NOT_TRACK'], '1')
        self.assertEqual(updated['env']['OTEL_METRICS_EXPORTER'], 'none')
        self.assertEqual(result['verification']['remaining_missing_settings_keys'], 0)

        supplement_yaml = Path(result['routing_files']['supplement_file']).read_text(encoding='utf-8')
        self.assertIn('PROCESS-NAME,Claude,MyProxy', supplement_yaml)
        self.assertIn('DOMAIN,bridge.claudeusercontent.com,MyProxy', supplement_yaml)
        self.assertIn('DOMAIN,browser-intake-us5-datadoghq.com,MyProxy', supplement_yaml)
        self.assertIn('DOMAIN,servd-anthropic-website.b-cdn.net,MyProxy', supplement_yaml)
        self.assertIn('IP-CIDR,160.79.104.0/21,MyProxy,no-resolve', supplement_yaml)
        self.assertIn('GEOSITE,category-ntp,MyProxy', supplement_yaml)
        self.assertTrue(Path(result['routing_files']['classical_list_file']).is_file())
        singbox_data = json.loads(Path(result['routing_files']['singbox_json_file']).read_text(encoding='utf-8'))
        self.assertEqual(singbox_data['version'], 2)
        self.assertIn('Claude', singbox_data['rules'][0]['process_name'])

    def test_telemetry_policy_reject_mode(self):
        out_dir = self.root / 'routing-reject'
        result = TR.apply_all(home=self.home, proxy_group='MyProxy', out_dir=out_dir, telemetry_policy='reject')
        supplement_yaml = Path(result['routing_files']['supplement_file']).read_text(encoding='utf-8')
        self.assertIn('DOMAIN,http-intake.logs.us5.datadoghq.com,REJECT', supplement_yaml)
        self.assertIn('DOMAIN,browser-intake-us5-datadoghq.com,REJECT', supplement_yaml)
        # Sift anti-fraud still routes through proxy to avoid IP mismatch lockouts:
        self.assertIn('DOMAIN-KEYWORD,sift,MyProxy', supplement_yaml)

    def test_existing_proxy_rules_are_not_duplicated_and_auto_patch_works(self):
        clash_dir = self.home / 'Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/profiles'
        clash_dir.mkdir(parents=True)
        proxy_cfg = self.file(
            'Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/profiles/Merge.yaml',
            'prepend-rules:\n  - DOMAIN-SUFFIX,claude.ai,🇺🇸 美国住宅 # 已有主站规则\n  - "PROCESS-NAME,Claude,🇺🇸 美国住宅"\n',
        )
        # Without passing proxy_group, it should auto-detect '🇺🇸 美国住宅' from existing claude.ai rule:
        before_report = TR.collect(home=self.home)
        self.assertEqual(before_report['routing']['present_rules_count'], 2)
        self.assertEqual(before_report['routing']['proxy_group'], '🇺🇸 美国住宅')
        self.assertEqual(before_report['routing']['auto_detected_proxy_group'], '🇺🇸 美国住宅')
        out_dir = self.root / 'routing-out'
        result = TR.apply_all(home=self.home, out_dir=out_dir, auto_patch_proxy=True)
        self.assertTrue(result['proxy_config_patch']['changed'])
        self.assertTrue(Path(result['proxy_config_patch']['backup']).is_file())
        patched_text = proxy_cfg.read_text(encoding='utf-8')
        self.assertEqual(patched_text.count('DOMAIN-SUFFIX,claude.ai,🇺🇸 美国住宅'), 1)
        self.assertEqual(patched_text.count('PROCESS-NAME,Claude,🇺🇸 美国住宅'), 1)
        self.assertIn('DOMAIN-SUFFIX,claude.com,🇺🇸 美国住宅', patched_text)
        self.assertIn('DOMAIN,assets-proxy.anthropic.com,🇺🇸 美国住宅', patched_text)
        after_report = TR.collect(home=self.home)
        self.assertEqual(after_report['routing']['missing_rules_count'], 0)

    def test_interactive_cancel_writes_nothing(self):
        with patch.object(sys, 'argv', ['telemetry_routing', '--interactive']), \
                patch('builtins.input', return_value='no'), \
                contextlib.redirect_stdout(io.StringIO()):
            code = TR.main()
        self.assertEqual(code, 3)
        self.assertFalse((self.home / '.claude/settings.json').exists())

    def test_launcher_generation_creates_executable_script(self):
        out_dir = self.root / 'desktop'
        out_dir.mkdir()
        launcher = TR.generate_launcher(out_dir=out_dir, proxy_group='Proxy', home=self.home)
        self.assertTrue(launcher.is_file())
        self.assertIn('telemetry_routing.py', launcher.read_text(encoding='utf-8'))

    def test_auto_patch_follows_zero_indent_rules_list(self):
        # Clash Verge writes "rules:" items at column 0; mixing "  - " into that list is a YAML error.
        proxy_cfg = self.file(
            'config/clash/config.yaml',
            'mode: rule\nrules:\n- DOMAIN-SUFFIX,claude.ai,MyProxy\n- MATCH,MyProxy\n',
        )
        result = TR.apply_all(home=self.home, out_dir=self.root / 'routing-zero', explicit_config=proxy_cfg)
        self.assertTrue(result['proxy_config_patch']['changed'])
        patched_text = proxy_cfg.read_text(encoding='utf-8')
        self.assertIn('\n- DOMAIN-SUFFIX,claude.com,MyProxy', patched_text)
        self.assertNotIn('\n  - ', patched_text)
        data = yaml.safe_load(patched_text)
        self.assertEqual(data['rules'][-1], 'MATCH,MyProxy')
        self.assertIn('DOMAIN-SUFFIX,claude.com,MyProxy', data['rules'])
        self.assertEqual(sum(1 for r in data['rules'] if r == 'DOMAIN-SUFFIX,claude.ai,MyProxy'), 1)

    def test_auto_patch_into_empty_rules_key_uses_key_indent(self):
        proxy_cfg = self.file('config/clash/config.yaml', 'mode: rule\nrules:\nproxies: []\n')
        TR.apply_all(home=self.home, out_dir=self.root / 'routing-empty', explicit_config=proxy_cfg, proxy_group='P')
        data = yaml.safe_load(proxy_cfg.read_text(encoding='utf-8'))
        self.assertIn('DOMAIN-SUFFIX,claude.ai,P', data['rules'])
        self.assertEqual(data['proxies'], [])

    def test_auto_patch_keeps_two_space_merge_indent(self):
        proxy_cfg = self.file(
            'config/clash/Merge.yaml',
            'prepend-rules:\n  # comment first\n  - DOMAIN-SUFFIX,claude.ai,P\nappend-rules: []\n',
        )
        TR.apply_all(home=self.home, out_dir=self.root / 'routing-two', explicit_config=proxy_cfg, proxy_group='P')
        data = yaml.safe_load(proxy_cfg.read_text(encoding='utf-8'))
        self.assertIn('DOMAIN-SUFFIX,claude.com,P', data['prepend-rules'])
        self.assertEqual(data['append-rules'], [])

    def test_auto_patch_targets_the_active_clash_verge_profile(self):
        base = 'Library/Application Support/io.github.clash-verge-rev.clash-verge-rev'
        self.file(f'{base}/profiles.yaml',
                  'current: abc123\nitems:\n- uid: Merge\n  type: merge\n  file: Merge.yaml\n'
                  '- uid: abc123\n  type: local\n  name: mine\n  file: abc123.yaml\n  option:\n    script: s1\n')
        merge = self.file(f'{base}/profiles/Merge.yaml', 'prepend-rules:\n  - DOMAIN-SUFFIX,claude.ai,OLD\n')
        profile = self.file(f'{base}/profiles/abc123.yaml', 'rules:\n- DOMAIN-SUFFIX,claude.ai,出口选择\n- MATCH,出口选择\n')
        result = TR.apply_all(home=self.home, out_dir=self.root / 'routing-active', auto_patch_proxy=True)
        self.assertEqual(Path(result['proxy_config_patch']['path']), profile)
        self.assertEqual(merge.read_text(encoding='utf-8'), 'prepend-rules:\n  - DOMAIN-SUFFIX,claude.ai,OLD\n')
        data = yaml.safe_load(profile.read_text(encoding='utf-8'))
        self.assertIn('DOMAIN-SUFFIX,claude.com,出口选择', data['rules'])
        self.assertNotIn('DOMAIN-SUFFIX,claude.com,OLD', data['rules'])
        self.assertEqual(data['rules'][-1], 'MATCH,出口选择')

    def test_auto_patch_falls_back_to_merge_without_profiles_index(self):
        base = 'Library/Application Support/io.github.clash-verge-rev.clash-verge-rev'
        merge = self.file(f'{base}/profiles/Merge.yaml', 'prepend-rules:\n  - DOMAIN-SUFFIX,claude.ai,P\n')
        result = TR.apply_all(home=self.home, out_dir=self.root / 'routing-fb', auto_patch_proxy=True)
        self.assertEqual(Path(result['proxy_config_patch']['path']), merge)

    def test_active_profile_with_unsafe_file_name_is_ignored(self):
        base = 'Library/Application Support/io.github.clash-verge-rev.clash-verge-rev'
        self.file(f'{base}/profiles.yaml', 'current: x\nitems:\n- uid: x\n  file: ../../etc/evil.yaml\n')
        folder = self.home / base
        self.assertIsNone(TR.active_profile_file(folder))


if __name__ == '__main__':
    unittest.main()
