"""Frozen cohort preparation and prevention of duplicate measured launches."""
import contextlib
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import repeated_benchmark as cohort

POLICY=cohort.ROOT/'tests/results/2026-11-04-rls-policy-development'
# The Critical contract now states row-level security, so every prepared
# Critical trial must declare that change against older baselines.
RLS=dict(contract_changes=('critical',),policy_record=POLICY/'README.md')


def frozen(controls):
    """Unchanged levels keep every control; a declared change may alter CONTRACT.md only."""
    return all(v['declared_contract_change_only'] and v['implementation_prompt_identical'] and v['grader_identical']
               if 'declared_contract_change_only' in v else all(v.values()) for v in controls.values())


class RepeatedBenchmarkTests(unittest.TestCase):
    def test_single_round_baseline_inherits_all_gates_and_blocks_in_shorthand(self):
        import shutil
        archive=cohort.ROOT/'tests/results/2026-11-04-lean-run-critical-high-pilot'
        extra=(archive/'name_resolution_probe.py',cohort.ROOT/'tests/probes/in_source_probe.py')
        with tempfile.TemporaryDirectory() as temp,contextlib.redirect_stdout(io.StringIO()):
            base=cohort.prepare(Path(temp)/'cohort',archive,levels=('high','critical'),repetitions=1,extra_probes=extra,**RLS)
            manifest=cohort.read(base/'manifest.json')
            self.assertEqual(manifest['baseline_repetitions_per_level'],1)
            self.assertEqual(len(manifest['known_quality_probes']),20)
            self.assertTrue(set(cohort.read(archive/'manifest.json')['known_quality_probes'])<=set(manifest['known_quality_probes']))
            b=cohort.harness(base/'harness-frozen.py');trial=base/'round-1/critical'
            for source in (archive/'round-1/critical/workspace').glob('*.py'):
                shutil.copyfile(source,trial/'workspace'/source.name)
            self.assertEqual(b.grade(base/'round-1','critical','in-source')['issues'],0)
            b.prepare_review(base/'round-1','critical')
            cohort.write(trial/'review-hashes.json',b.digest_tree(trial/'reviewspace'))
            (trial/'review').mkdir()
            cohort.write(trial/'review/final.txt',{'status':'PASS','findings':[]})
            with patch.object(cohort,'cross_regressions',return_value=[]):
                assessment=cohort.assess(base,b,1,'critical',1,'in-source-grade.json')
            self.assertEqual({name for name,p in assessment['critical_probes'].items() if not p['passed']},{'in_source_probe.py'})
            self.assertEqual(assessment['critical_probes']['in_source_probe.py']['report']['failed_cases'],6)
            self.assertIn('known_quality_probes',assessment['blockers'])

    def test_selected_single_round_prepares_only_requested_tasks(self):
        archive=cohort.ROOT/'tests/results/2026-11-04-lean-run-critical-high'
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            base=cohort.prepare(Path(temp)/'cohort',archive,levels=('high','critical'),repetitions=1,**RLS)
            manifest=cohort.read(base/'manifest.json')
            self.assertEqual(manifest['orders'],[['high','critical']])
            self.assertEqual(manifest['repetitions_per_level'],1)
            self.assertEqual(manifest['baseline_repetitions_per_level'],3)
            self.assertEqual(set(cohort.read(base/'controls.json')),{'round-1/high','round-1/critical'})
            self.assertFalse((base/'round-1/medium').exists())
            self.assertFalse((base/'round-2').exists())
            self.assertTrue(frozen(cohort.read(base/'controls.json')))
            self.assertTrue(set(cohort.SETTING_PROBE_NAMES)<=set(manifest['known_quality_probes']))

    def test_final_two_findings_cannot_pass_original_grader_and_coordinator_gate(self):
        import shutil
        archive=cohort.ROOT/'tests/results/2026-11-04-lean-run-critical-high'
        probe=cohort.ROOT/'tests/probes/critical_final_findings_probe.py'
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            base=cohort.prepare(Path(temp)/'cohort',archive,levels=('critical',),repetitions=1,extra_probes=(probe,),
                               superseded=POLICY/'superseded-expectations.json',**RLS)
            self.assertEqual((base/probe.name).read_bytes(),probe.read_bytes())
            b=cohort.harness(base/'harness-frozen.py');trial=base/'round-1/critical'
            for source in (archive/'round-3/critical/workspace').glob('*.py'):
                shutil.copyfile(source,trial/'workspace'/source.name)
            self.assertEqual(b.grade(base/'round-1','critical','final-findings')['issues'],0)
            b.prepare_review(base/'round-1','critical')
            cohort.write(trial/'review-hashes.json',b.digest_tree(trial/'reviewspace'))
            (trial/'review').mkdir()
            cohort.write(trial/'review/final.txt',{'status':'PASS','findings':[]})
            with patch.object(cohort,'cross_regressions',return_value=[]):
                assessment=cohort.assess(base,b,1,'critical',1,'final-findings-grade.json')
            self.assertIn('known_quality_probes',assessment['blockers'])
            self.assertEqual(assessment['critical_probes'][probe.name]['report']['failed_cases'],3)
            self.assertFalse(assessment['critical_probes'][probe.name]['passed'])
            self.assertFalse(assessment['critical_probes'][probe.name]['superseded_only'])

    def test_nine_initial_workspaces_and_fixed_controls_without_clobber(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            base=cohort.prepare(Path(temp)/'cohort',**RLS)
            manifest=cohort.read(base/'manifest.json')
            self.assertEqual(manifest['repetitions_per_level'],3)
            self.assertEqual(manifest['baseline_repetitions_per_level'],1)
            controls=cohort.read(base/'controls.json')
            self.assertEqual(len(controls),9)
            self.assertTrue(frozen(controls))
            for slot in range(3):
                self.assertEqual({row[slot] for row in manifest['orders']},{'medium','high','critical'})
            for number in range(1,4):
                for level,issues in [('medium',3),('high',5),('critical',8)]:
                    trial=base/f'round-{number}'/level
                    self.assertEqual(cohort.read(trial/'baseline-grade.json')['issues'],issues)
                    self.assertTrue((trial/'workspace/.agents/skills/lean-run/scripts/check.py').is_file())
            before=(base/'manifest.json').read_bytes()
            with self.assertRaises(ValueError):cohort.prepare(base)
            self.assertEqual((base/'manifest.json').read_bytes(),before)

    def test_undeclared_or_unrecorded_contract_change_is_refused(self):
        archive=cohort.ROOT/'tests/results/2026-11-04-lean-run-in-source-budget'
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(AssertionError):
                cohort.prepare(Path(temp)/'silent',archive,levels=('critical',),repetitions=1)
            with self.assertRaises(ValueError):
                cohort.prepare(Path(temp)/'unrecorded',archive,levels=('critical',),repetitions=1,contract_changes=('critical',))
            with self.assertRaises(ValueError):
                cohort.prepare(Path(temp)/'unselected',archive,levels=('high',),repetitions=1,**RLS)
            with self.assertRaises(AssertionError):
                cohort.prepare(Path(temp)/'unchanged',archive,levels=('high',),repetitions=1,
                               contract_changes=('high',),policy_record=POLICY/'README.md')

    def test_new_baseline_separates_policy_superseded_failures_from_blocking_ones(self):
        import shutil
        archive=cohort.ROOT/'tests/results/2026-11-04-lean-run-in-source-budget'
        posthoc=[archive/name for name in ('foreign_guard_probe.py','review2_guard_probe.py','final_guard_probe.py')]
        extra=(cohort.ROOT/'tests/probes/rls_policy_probe.py',*posthoc)
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            base=cohort.prepare(Path(temp)/'cohort',archive,levels=('high','critical'),repetitions=1,extra_probes=extra,
                                superseded=POLICY/'superseded-expectations.json',**RLS)
            manifest=cohort.read(base/'manifest.json')
            self.assertEqual(manifest['contract_changed_levels'],['critical'])
            self.assertEqual(manifest['comparison_valid_levels'],['high'])
            self.assertEqual(manifest['regression_archives'],[str(archive),*cohort.read(archive/'manifest.json')['regression_archives']])
            self.assertEqual((manifest['coordinator_gate_levels'],manifest['optimization_level']),(['critical'],'high'))
            self.assertEqual(len(manifest['known_quality_probes']),24)
            self.assertEqual((base/'policy-record.md').read_bytes(),(POLICY/'README.md').read_bytes())
            controls=cohort.read(base/'controls.json')
            self.assertTrue(all(controls['round-1/high'].values()))
            self.assertTrue(controls['round-1/critical']['declared_contract_change_only'])
            self.assertIn('Row-level security',(base/'round-1/critical/initial/CONTRACT.md').read_text())
            b=cohort.harness(base/'harness-frozen.py');trial=base/'round-1/critical'
            for source in (archive/'round-1/critical/workspace').glob('*.py'):
                shutil.copyfile(source,trial/'workspace'/source.name)
            shutil.copyfile(POLICY/'prototype/vault_guard.py',trial/'workspace/vault_guard.py')
            self.assertEqual(b.grade(base/'round-1','critical','prototype')['issues'],0)
            b.prepare_review(base/'round-1','critical')
            cohort.write(trial/'review-hashes.json',b.digest_tree(trial/'reviewspace'))
            (trial/'review').mkdir()
            cohort.write(trial/'review/final.txt',{'status':'PASS','findings':[]})
            assessment=cohort.assess(base,b,1,'critical',1,'prototype-grade.json')
            self.assertEqual(assessment['blockers'],[])
            historical=[row for row in assessment['cross'] if row['direction']=='historical_tests_on_candidate']
            self.assertEqual(len(historical),5)
            self.assertTrue(all(row['superseded_only'] for row in historical))
            self.assertEqual(assessment['policy_superseded']['probes'],cohort.read(POLICY/'superseded-expectations.json')['probe_cases'])
            self.assertFalse(assessment['critical_probes']['critical_final_findings_probe.py']['passed'])
            self.assertTrue(assessment['critical_probes']['rls_policy_probe.py']['passed'])
            # Remove one recorded expectation: that suite's failure must block again.
            value=cohort.read(base/'superseded-expectations.json')
            value['historical_tests'][f'{archive.name}/round-1'].pop()
            cohort.write(base/'superseded-expectations.json',value)
            assessment=cohort.assess(base,b,1,'critical',1,'prototype-grade.json')
            self.assertEqual(assessment['blockers'],['historical_regressions'])

    def test_probe_case_ids_require_a_complete_count(self):
        report={'failed_cases':2,'cases':[{'case':'x','journal':'WAL','interface':'API','passed':False},
                                          {'interface':'CLI','should_fail':True,'passed':False},{'case':'ok','pass':True}]}
        self.assertEqual(cohort.failed_probe_cases(report),['case=x/journal=WAL/interface=API','interface=CLI/should_fail=True'])
        self.assertIsNone(cohort.failed_probe_cases(dict(report,failed_cases=3)))
        self.assertEqual(cohort.failed_probe_cases({'failed_cases':1,'cases':{'a':{'failures':['x']},'b':{'failures':[]}}}),['a'])
        self.assertIsNone(cohort.failed_probe_cases({'failed_cases':1}))

    def test_unselected_baseline_target_is_not_inherited(self):
        archive=cohort.ROOT/'tests/results/2026-11-04-lean-run-in-source-budget'
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            base=cohort.prepare(Path(temp)/'cohort',archive,levels=('critical',),repetitions=1,**RLS)
            manifest=cohort.read(base/'manifest.json')
            self.assertNotIn('optimization_level',manifest)
            self.assertEqual(manifest['coordinator_gate_levels'],['critical'])

    def test_contract_gates_require_a_satisfying_reference(self):
        archive=cohort.ROOT/'tests/results/2026-11-04-lean-run-in-source-budget'
        contract=cohort.ROOT/'tests/probes/critical_contract_probe.py'
        reference=cohort.ROOT/'tests/benchmark/reference/critical'
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            base=cohort.prepare(Path(temp)/'cohort',archive,levels=('critical',),repetitions=1,
                                mandatory_probes=(contract,),references={'critical':reference},**RLS)
            manifest=cohort.read(base/'manifest.json')
            self.assertEqual((manifest['gate_policy'],manifest['mandatory_probes']),('contract',[contract.name]))
            self.assertIn(contract.name,manifest['known_quality_probes'])
            self.assertNotIn(contract.name,manifest['advisory_probes'])
            check=cohort.read(base/'reference-check.json')['critical']
            self.assertTrue(check['reference_passes_all'] and check['initial_fails_some'])
            self.assertFalse(check['initial'][contract.name])
            # A candidate that leaks foreign data cannot serve as the reference.
            with self.assertRaisesRegex(ValueError,'not satisfiable'):
                cohort.prepare(Path(temp)/'leaky',archive,levels=('critical',),repetitions=1,mandatory_probes=(contract,),
                               references={'critical':archive/'round-1/critical/workspace'},**RLS)
            with self.assertRaises(ValueError):
                cohort.prepare(Path(temp)/'missing',archive,levels=('critical',),repetitions=1,mandatory_probes=(contract,),**RLS)

    def test_inherited_identical_probe_can_stay_mandatory(self):
        # A contract-policy baseline already carries its mandatory probe; reusing it must not collide.
        archive=cohort.ROOT/'tests/results/2026-11-05-lean-run-contract-gates'
        contract=cohort.ROOT/'tests/probes/critical_contract_probe.py'
        reference=cohort.ROOT/'tests/benchmark/reference/critical'
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            base=cohort.prepare(Path(temp)/'cohort',archive,levels=('critical',),repetitions=1,
                                mandatory_probes=(contract,),references={'critical':reference},**RLS)
            manifest=cohort.read(base/'manifest.json')
            self.assertEqual(manifest['mandatory_probes'],[contract.name])
            self.assertNotIn(contract.name,manifest['advisory_probes'])
            self.assertEqual(manifest['known_quality_probes'].count(contract.name),1)
            changed=Path(temp)/'changed'/contract.name;changed.parent.mkdir()
            changed.write_text(contract.read_text()+'\n# changed\n')
            with self.assertRaisesRegex(ValueError,'distinct'):
                cohort.prepare(Path(temp)/'changed-cohort',archive,levels=('critical',),repetitions=1,
                               mandatory_probes=(changed,),references={'critical':reference},**RLS)

    def test_contract_policy_blocks_only_on_mandatory_gates(self):
        import shutil
        archive=cohort.ROOT/'tests/results/2026-11-04-lean-run-in-source-budget'
        contract=cohort.ROOT/'tests/probes/critical_contract_probe.py'
        reference=cohort.ROOT/'tests/benchmark/reference/critical'
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            base=cohort.prepare(Path(temp)/'cohort',archive,levels=('critical',),repetitions=1,
                                mandatory_probes=(contract,),references={'critical':reference},**RLS)
            b=cohort.harness(base/'harness-frozen.py');trial=base/'round-1/critical'
            for label,source in (('reference',reference),('leaky',archive/'round-1/critical/workspace')):
                for path in source.glob('*.py'):
                    if not path.name.startswith('test_'):shutil.copyfile(path,trial/'workspace'/path.name)
                b.grade(base/'round-1','critical',label)
                if (trial/'reviewspace').exists():shutil.rmtree(trial/'reviewspace')
                b.prepare_review(base/'round-1','critical')
                cohort.write(trial/'review-hashes.json',b.digest_tree(trial/'reviewspace'))
                (trial/'review').mkdir(exist_ok=True)
                cohort.write(trial/'review/final.txt',{'status':'PASS','findings':[]})
                with patch.object(cohort,'cross_regressions',return_value=[{'direction':'historical_tests_on_candidate',
                        'exit_code':1,'baseline_archive':str(archive),'baseline_round':1,'log':'x.log'}]):
                    assessment=cohort.assess(base,b,1,'critical',1,f'{label}-grade.json')
                self.assertNotIn('historical_regressions',assessment['blockers'])
                self.assertEqual(len(assessment['advisory']['historical_suites_failing']),1)
                if label=='reference':
                    self.assertEqual(assessment['blockers'],[])
                    self.assertTrue(assessment['critical_probes'][contract.name]['passed'])
                else:
                    self.assertEqual(assessment['blockers'],['mandatory_probes'])
                    self.assertIn('rls_policy_probe.py',assessment['advisory']['probes']) if 'rls_policy_probe.py' in assessment['critical_probes'] else None

    def test_rejected_findings_need_contract_policy_and_evidence(self):
        for policy,outcome in (('contract','DONE'),(None,AssertionError)):
            with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
                base=Path(temp);(base/'harness-frozen.py').write_text('')
                manifest={'orders':[['high']]}
                if policy:manifest['gate_policy']=policy
                cohort.write(base/'manifest.json',manifest)
                trial=base/'round-1/high';(trial/'review').mkdir(parents=True)
                review={'status':'REWORK','findings':[{'id':'R1'}]}
                cohort.write(trial/'review/final.txt',review)
                cohort.write(trial/'assessment-1.json',{'blockers':['independent_review'],'grade':'grade.json','review':review})
                cohort.write(trial/'assessment-1-adjudication.json',{'reason':'oracle','evidence':['probe.json'],
                    'noncontract_blockers':[],'rejected_findings':[{'id':'R1','reason':'not contract-traceable','evidence':'oracle run'}]})
                if outcome=='DONE':
                    self.assertEqual(cohort.run(base),0)
                    self.assertEqual(cohort.read(trial/'result.json')['status'],'DONE')
                else:
                    with self.assertRaises(AssertionError):cohort.run(base)

    def test_failure_headers_require_a_complete_count(self):
        log='FAIL: test_a (m.C.test_a) (x=1)\nERROR: test_b (m.C.test_b)\n\nFAILED (failures=1, errors=1)\n'
        self.assertEqual(cohort.failure_headers(log),['test_a (m.C.test_a) (x=1)','test_b (m.C.test_b)'])
        self.assertIsNone(cohort.failure_headers(log.replace('errors=1','errors=2')))
        self.assertEqual(cohort.failure_headers('Ran 0 tests\nOK\n'),[])

    def test_incomplete_phase_does_not_launch_again(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            base=Path(temp)
            (base/'round-1/medium/implementation').mkdir(parents=True)
            launched=[]
            fake=SimpleNamespace(run=lambda *args:launched.append(args))
            with self.assertRaisesRegex(RuntimeError,'Incomplete phase'):
                cohort.run_phase(base,fake,1,'medium','implementation')
            self.assertEqual(launched,[])

    def test_latest_repeated_baseline_preserves_inputs_and_all_known_probes(self):
        archive=cohort.ROOT/'tests/results/2026-11-03-lean-run-repeated'
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            base=cohort.prepare(Path(temp)/'cohort',archive,**RLS)
            manifest=cohort.read(base/'manifest.json')
            self.assertEqual(manifest['baseline_repetitions_per_level'],3)
            self.assertEqual(set(manifest['known_quality_probes']),set(cohort.PROBE_NAMES))
            self.assertTrue(frozen(cohort.read(base/'controls.json')))

    def test_latest_followups_are_frozen_and_block_a_passing_review(self):
        import shutil
        archive=cohort.ROOT/'tests/results/2026-11-03-lean-run-critical-medium'
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            base=cohort.prepare(Path(temp)/'cohort',archive,**RLS)
            self.assertEqual(set(cohort.read(base/'manifest.json')['known_quality_probes']),
                             {*cohort.PROBE_NAMES,*cohort.FOLLOWUP_PROBE_NAMES})
            b=cohort.harness(base/'harness-frozen.py')
            for number,script in enumerate(cohort.FOLLOWUP_PROBE_NAMES,1):
                trial=base/f'round-{number}/critical'
                self.assertEqual((base/script).read_bytes(),(archive/script).read_bytes())
                for source in (archive/f'round-{number}/critical/workspace').glob('*.py'):
                    shutil.copyfile(source,trial/'workspace'/source.name)
                self.assertEqual(b.grade(base/f'round-{number}','critical','known-regression')['issues'],0)
                b.prepare_review(base/f'round-{number}','critical')
                cohort.write(trial/'review-hashes.json',b.digest_tree(trial/'reviewspace'))
                (trial/'review').mkdir()
                cohort.write(trial/'review/final.txt',{'status':'PASS','findings':[]})
                with patch.object(cohort,'cross_regressions',return_value=[]):
                    a=cohort.assess(base,b,number,'critical',1,'known-regression-grade.json')
                self.assertIn('known_quality_probes',a['blockers'])
                self.assertFalse(a['critical_probes'][script]['passed'])

    def test_known_regression_blocks_a_passing_original_grader_and_review(self):
        import shutil
        archive=cohort.ROOT/'tests/results/2026-11-03-lean-run-repeated'
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            base=cohort.prepare(Path(temp)/'cohort',archive,**RLS)
            b=cohort.harness(base/'harness-frozen.py');trial=base/'round-1/critical'
            for source in (archive/'round-3/critical/workspace').glob('*.py'):
                shutil.copyfile(source,trial/'workspace'/source.name)
            grade=b.grade(base/'round-1','critical','known-regression')
            self.assertEqual(grade['issues'],0)
            b.prepare_review(base/'round-1','critical')
            cohort.write(trial/'review-hashes.json',b.digest_tree(trial/'reviewspace'))
            (trial/'review').mkdir()
            cohort.write(trial/'review/final.txt',{'status':'PASS','findings':[]})
            with patch.object(cohort,'cross_regressions',return_value=[]):
                assessment=cohort.assess(base,b,1,'critical',1,'known-regression-grade.json')
            self.assertIn('known_quality_probes',assessment['blockers'])
            self.assertFalse(assessment['critical_probes']['ignored_update_probe.py']['passed'])

    def test_promoted_sql_separator_probe_blocks_prior_final_failure(self):
        import shutil
        archive=cohort.ROOT/'tests/results/2026-11-04-lean-run-critical-speed'
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            base=cohort.prepare(Path(temp)/'cohort',archive,**RLS)
            manifest=cohort.read(base/'manifest.json')
            self.assertEqual(set(manifest['known_quality_probes']),
                             {*cohort.PROBE_NAMES,*cohort.FOLLOWUP_PROBE_NAMES,*cohort.EFFECT_PROBE_NAMES})
            b=cohort.harness(base/'harness-frozen.py')
            trial=base/'round-1/critical'
            for source in (archive/'round-1/critical/workspace').glob('*.py'):
                shutil.copyfile(source,trial/'workspace'/source.name)
            self.assertEqual(b.grade(base/'round-1','critical','separator-regression')['issues'],0)
            b.prepare_review(base/'round-1','critical')
            cohort.write(trial/'review-hashes.json',b.digest_tree(trial/'reviewspace'))
            (trial/'review').mkdir()
            cohort.write(trial/'review/final.txt',{'status':'PASS','findings':[]})
            with patch.object(cohort,'cross_regressions',return_value=[]):
                assessment=cohort.assess(base,b,1,'critical',1,'separator-regression-grade.json')
            failed={name for name,probe in assessment['critical_probes'].items() if not probe['passed']}
            self.assertEqual(failed,{'trigger_separator_probe.py'})
            self.assertIn('known_quality_probes',assessment['blockers'])

    def test_probes_can_import_local_application_helpers(self):
        import shutil
        archive=cohort.ROOT/'tests/results/2026-11-03-lean-run-critical-medium'
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            base=cohort.prepare(Path(temp)/'cohort',archive,**RLS)
            b=cohort.harness(base/'harness-frozen.py');trial=base/'round-3/critical';workspace=trial/'workspace'
            for source in (archive/'round-3/critical/workspace').glob('*.py'):
                shutil.copyfile(source,workspace/source.name)
            (workspace/'vault.py').rename(workspace/'fixture_impl.py')
            (workspace/'vault.py').write_text('from fixture_impl import *\n')
            self.assertEqual(b.grade(base/'round-3','critical','split-module')['issues'],0)
            b.prepare_review(base/'round-3','critical')
            cohort.write(trial/'review-hashes.json',b.digest_tree(trial/'reviewspace'))
            (trial/'review').mkdir()
            cohort.write(trial/'review/final.txt',{'status':'PASS','findings':[]})
            with patch.object(cohort,'cross_regressions',return_value=[]):
                assessment=cohort.assess(base,b,3,'critical',1,'split-module-grade.json')
            self.assertTrue(all(v['passed'] for v in assessment['critical_probes'].values()))

    def test_terminal_failure_is_retained_and_other_results_can_close(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            base=Path(temp);(base/'harness-frozen.py').write_text('')
            cohort.write(base/'manifest.json',{'orders':[['medium','high']]})
            trial=base/'round-1/medium';(trial/'review').mkdir(parents=True)
            cohort.write(trial/'review/final.txt',{'status':'REWORK','findings':[{'id':'unresolved'}]})
            for index in range(1,4):
                cohort.write(trial/f'assessment-{index}.json',{'blockers':['independent_review'],
                    'grade':'grade.json','review':{'status':'REWORK','findings':[{'id':'unresolved'}]}})
            for index in (1,2):cohort.write(trial/f'repair-{index}-request.json',{'findings':[{'id':'unresolved'}]})
            other=base/'round-1/high';other.mkdir()
            cohort.write(other/'result.json',{'status':'DONE'})
            self.assertEqual(cohort.run(base),3)
            self.assertEqual(cohort.read(trial/'result.json')['status'],'FAILED')
            self.assertEqual(cohort.read(other/'result.json')['status'],'DONE')
            self.assertEqual(cohort.read(base/'progress.json')['state'],'COMPLETE_WITH_FAILURES')


if __name__=='__main__':unittest.main()
