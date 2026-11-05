"""An identical repeated cohort must compare to itself with zero change."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import summarize_repeated_benchmark as report


class SummaryTests(unittest.TestCase):
    def test_selected_single_round_uses_one_sample_and_all_three_baseline_rounds(self):
        baseline=Path(__file__).resolve().parent/'results/2026-11-04-lean-run-critical-high'
        with tempfile.TemporaryDirectory(prefix='lean-summary-single-') as temporary:
            root=Path(temporary)/'cohort'
            shutil.copytree(baseline,root,ignore=shutil.ignore_patterns(
                'validation-logs','__pycache__','archive-sha256.json'))
            manifest=report.read(root/'manifest.json')
            manifest.update(baseline_archive=str(baseline),orders=[['high','critical']],repetitions_per_level=1)
            report.write(root/'manifest.json',manifest)
            with contextlib.redirect_stdout(io.StringIO()):report.summarize(root)
            summary=report.read(root/'summary.json')
            self.assertEqual([row['level'] for row in summary['levels']],['high','critical'])
            self.assertEqual(len(summary['trials']),2)
            for row in summary['levels']:
                self.assertEqual((row['candidate_n'],row['baseline_n']),(1,3))
                self.assertEqual(row['statistics']['measured_seconds']['requested_n'],1)
                self.assertIsNone(row['statistics']['measured_seconds']['sample_sd'])
                self.assertAlmostEqual(sum(row['candidate_phase_means'].values()),row['statistics']['measured_seconds']['mean'])
            self.assertEqual(summary['quality']['passed_trials'],1)
            self.assertNotIn('actual_nine_trial_consumption',summary['totals'])
            self.assertAlmostEqual(summary['levels'][0]['statistics']['measured_seconds']['mean'],643.452)
            self.assertAlmostEqual(summary['levels'][0]['baseline']['measured_seconds'],587.791)
            self.assertIsNone(summary['levels'][1]['mean_change_percent']['uncached_input_tokens'])
            trial=root/'round-1/critical'
            result=report.read(trial/'result.json')
            path=trial/f"assessment-{result['final_assessment']}.json"
            assessment=report.read(path)
            followup={'source_sha256':assessment['candidate_sha256']['vault.py'],
                      'cases':[{}, {}], 'failed_cases':1}
            assessment['coordinator_probes']={'name_resolution_probe.py':{'report':followup,'passed':False}}
            report.write(path,assessment)
            with contextlib.redirect_stdout(io.StringIO()):report.summarize(root)
            updated=report.read(root/'summary.json')
            self.assertEqual(updated['quality']['final_posthoc_probe_failed_cases'],
                             summary['quality']['final_posthoc_probe_failed_cases']+1)
            self.assertEqual(updated['quality']['final_added_probe_failed_cases'],
                             summary['quality']['final_added_probe_failed_cases'])
            self.assertEqual(updated['trials'][1]['posthoc_probes']['name_resolution_probe.py']['executed_cases'],2)
            followup['source_sha256']='stale'
            report.write(path,assessment)
            with self.assertRaises(AssertionError),contextlib.redirect_stdout(io.StringIO()):
                report.summarize(root)

    def test_unknown_baseline_mean_does_not_suppress_known_candidate_mean(self):
        archives=Path(__file__).resolve().parent/'results'
        baseline=archives/'2026-11-03-lean-run-critical-medium'
        with tempfile.TemporaryDirectory(prefix='lean-unknown-baseline-') as temporary:
            root=Path(temporary)/'cohort'
            shutil.copytree(archives/'2026-11-03-lean-run-repeated',root,
                            ignore=shutil.ignore_patterns('development-candidate','archive-sha256.json'))
            manifest=report.read(root/'manifest.json')
            manifest.update(baseline_archive=str(baseline),optimization_level='critical')
            report.write(root/'manifest.json',manifest)
            with contextlib.redirect_stdout(io.StringIO()):report.summarize(root)
            summary=report.read(root/'summary.json');critical=summary['levels'][2]
            self.assertIsNone(critical['baseline']['uncached_input_tokens'])
            self.assertIsNotNone(critical['statistics']['uncached_input_tokens']['mean'])
            self.assertIsNone(critical['mean_change_percent']['uncached_input_tokens'])
            self.assertAlmostEqual(sum(critical['candidate_phase_means'].values()),
                                   critical['statistics']['measured_seconds']['mean'])
            self.assertIsNone(summary['totals']['baseline_one_of_each_level']['total_tokens'])
            self.assertEqual(summary['optimization_target']['level'],'critical')

    def test_posthoc_failures_are_separate_and_cannot_be_reported_as_passing_quality(self):
        baseline=Path(__file__).resolve().parent/'results/2026-11-03-lean-run-repeated'
        with tempfile.TemporaryDirectory(prefix='lean-summary-followup-') as temporary:
            root=Path(temporary)/'cohort'
            shutil.copytree(baseline,root,ignore=shutil.ignore_patterns(
                'development-candidate','validation-logs','__pycache__','archive-sha256.json'))
            manifest=report.read(root/'manifest.json');manifest['baseline_archive']=str(baseline)
            report.write(root/'manifest.json',manifest)
            report.write(root/'followup-protocol.json',{'scope':'Synthetic reporter test; no model calls.'})
            for number in (1,2,3):
                source=root/f'round-{number}/critical/workspace/vault.py'
                for name in ('frame-followup','trigger-compatibility'):
                    value={'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                           'failed_cases':1 if number==1 else 0,'cases':[{}],
                           'finding_groups':{'example':number==1}}
                    report.write(root/f'{name}-round-{number}-final.json',value)
                    report.write(root/f'{name}-baseline-{number}.json',value)
            with contextlib.redirect_stdout(io.StringIO()):report.summarize(root)
            summary=report.read(root/'summary.json')
            self.assertEqual(summary['quality']['final_posthoc_probe_failed_cases'],2)
            self.assertEqual(summary['posthoc_followup']['probes']['frame-followup']['candidate_failed_cases'],[1,0,0])
            self.assertEqual(summary['quality']['passed_trials'],7)
            assessment=root/'round-1/critical/assessment-3.json'
            value=report.read(assessment)
            value['coordinator_findings']=[{'id':'COORD-SYNTHETIC','severity':'HIGH'}]
            report.write(assessment,value)
            with contextlib.redirect_stdout(io.StringIO()):report.summarize(root)
            self.assertEqual(report.read(root/'summary.json')['quality']['final_coordinator_findings'],1)
            # Round 2 was independently PASS; a new demonstrated failure must block that claim.
            path=root/'frame-followup-round-2-final.json'
            value=report.read(path);value['failed_cases']=1;report.write(path,value)
            with self.assertRaises(AssertionError),contextlib.redirect_stdout(io.StringIO()):
                report.summarize(root)
            value['failed_cases']=0;report.write(path,value)
            trial=root/'round-2/critical'
            result=report.read(trial/'result.json')
            path=trial/f"assessment-{result['final_assessment']}.json"
            assessment=report.read(path)
            # A failed probe can also have zero failed cases when its execution aborts.
            assessment['coordinator_probes']={'new_probe.py':{'passed':False,'report':{
                'source_sha256':assessment['candidate_sha256']['vault.py'],'failed_cases':0,'cases':[]}}}
            report.write(path,assessment)
            with self.assertRaises(AssertionError),contextlib.redirect_stdout(io.StringIO()):
                report.summarize(root)

    def test_repeated_self_comparison_keeps_failed_costs_and_has_zero_delta(self):
        baseline=Path(__file__).resolve().parent/'results/2026-11-03-lean-run-repeated'
        with tempfile.TemporaryDirectory(prefix='lean-summary-check-') as temporary:
            root=Path(temporary)/'cohort'
            shutil.copytree(baseline,root,ignore=shutil.ignore_patterns(
                'development-candidate','validation-logs','__pycache__','archive-sha256.json'))
            manifest=report.read(root/'manifest.json')
            manifest['baseline_archive']=str(baseline)
            manifest['baseline_repetitions_per_level']=3
            report.write(root/'manifest.json',manifest)
            with contextlib.redirect_stdout(io.StringIO()):report.summarize(root)
            summary=report.read(root/'summary.json')
            for level in summary['levels']:
                self.assertEqual((level['baseline_n'],level['candidate_n']),(3,3))
                self.assertTrue(all(abs(delta)<1e-9 for delta in level['mean_change_percent'].values()))
                self.assertAlmostEqual(level['implementation_time_change_percent'],0)
            self.assertEqual(summary['quality']['passed_trials'],7)
            self.assertEqual(len(summary['quality']['failed_trials']),2)
            self.assertEqual(summary['totals']['actual_nine_trial_consumption']['total_tokens'],7145208)

    def test_timeout_usage_stays_unknown_and_elapsed_cost_is_retained(self):
        baseline=Path(__file__).resolve().parent/'results/2026-11-03-lean-run-repeated'
        with tempfile.TemporaryDirectory(prefix='lean-summary-timeout-') as temporary:
            root=Path(temporary)/'cohort'
            shutil.copytree(baseline,root,ignore=shutil.ignore_patterns(
                'development-candidate','validation-logs','__pycache__','archive-sha256.json'))
            manifest=report.read(root/'manifest.json');manifest['baseline_archive']=str(baseline)
            report.write(root/'manifest.json',manifest)
            trial=root/'round-1/medium';phase=trial/'implementation'
            metric=report.read(phase/'metrics.json');original_tokens=metric['total_tokens']
            metric.update(usage=None,elapsed_seconds=900.0,exit_code=-15,timed_out=True,completed_turns=0)
            metric.pop('total_tokens');metric.pop('uncached_input_tokens')
            report.write(phase/'metrics.json',metric)
            events=[line for line in (phase/'events.jsonl').read_text().splitlines()
                    if json.loads(line).get('type')!='turn.completed']
            (phase/'events.jsonl').write_text('\n'.join(events)+'\n')
            result=report.read(trial/'result.json');result.update(status='TIMEOUT',quality_status='PASS')
            report.write(trial/'result.json',result)
            with contextlib.redirect_stdout(io.StringIO()):report.summarize(root)
            summary=report.read(root/'summary.json');medium=summary['levels'][0]
            self.assertIsNone(medium['statistics']['uncached_input_tokens']['mean'])
            self.assertEqual(medium['statistics']['uncached_input_tokens']['n'],2)
            self.assertEqual(medium['statistics']['uncached_input_tokens']['requested_n'],3)
            self.assertGreater(medium['statistics']['measured_seconds']['mean'],500)
            self.assertIsNone(summary['totals']['actual_nine_trial_consumption']['total_tokens'])
            self.assertEqual(summary['totals']['known_consumption_lower_bound']['total_tokens'],7145208-original_tokens)
            self.assertIn('round-1/medium',summary['quality']['incomplete_execution_trials'])


if __name__=='__main__':unittest.main()
