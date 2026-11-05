"""Opt-in sequential cohort of level_benchmark; real CLI usage."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / 'tests/results/2026-11-03-lean-run-optimized'
ORDERS = [('medium','high','critical'), ('high','critical','medium'), ('critical','medium','high')]
PROBE_NAMES = ('supplemental_probe.py', 'after_trigger_probe.py', 'audit_followup_probe.py',
               'preservation_probe.py', 'noop_probe.py', 'read_isolation_probe.py',
               'ignored_update_probe.py')
FOLLOWUP_PROBE_NAMES = ('frame_followup_probe.py', 'trigger_compatibility_probe.py')
EFFECT_PROBE_NAMES = ('dollar_identifier_probe.py', 'trigger_counter_probe.py',
                      'unicode_space_probe.py', 'trigger_separator_probe.py',
                      'malformed_effect_probe.py')
SETTING_PROBE_NAMES = ('storage_encoding_probe.py', 'trigger_ignore_scope_probe.py',
                      'recursive_setting_probe.py')


def read(path):
    value=path.read_text().strip()
    if value.startswith('```'): value='\n'.join(value.splitlines()[1:-1])
    return json.loads(value)


def write(path,value):
    path.write_text(json.dumps(value,indent=2)+'\n')


def harness(path):
    spec=importlib.util.spec_from_file_location('frozen_benchmark',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def baseline_trial(archive, level, number=1):
    repeated=archive/f'round-{number}'/level
    return repeated if repeated.is_dir() else archive/level


def baseline_count(archive):
    rows=read(archive/'summary.json')['levels']
    counts={row.get('candidate_n',1) for row in rows}
    if len(counts)!=1:raise ValueError('Baseline levels must have the same sample count')
    return counts.pop()


def prepare(destination, baseline=None, levels=('medium','high','critical'), repetitions=3, extra_probes=()):
    destination=destination.resolve()
    baseline=(baseline or BASELINE).resolve()
    if repetitions not in (1,2,3) or not levels or len(set(levels))!=len(levels) or any(level not in ('medium','high','critical') for level in levels):
        raise ValueError('Select distinct known levels and 1–3 repetitions')
    orders=[tuple(levels[n % len(levels):])+tuple(levels[:n % len(levels)]) for n in range(repetitions)]
    if destination.exists() or destination==ROOT or ROOT in destination.parents:
        raise ValueError('Use a new directory outside the repository')
    destination.mkdir(parents=True)
    b=harness(ROOT/'tests/level_benchmark.py')
    controls={}
    for number,order in enumerate(orders,1):
        base=b.prepare(destination/f'round-{number}',levels=order)
        for level in order:
            trial=base/level
            prior=baseline_trial(baseline,level,number)
            old=b.digest_tree(prior/'initial');new=b.digest_tree(trial/'initial')
            checks={'non_skill_initial_files_identical':{k:v for k,v in old.items() if not k.startswith('.agents/')}=={k:v for k,v in new.items() if not k.startswith('.agents/')},
                    'implementation_prompt_identical':(trial/'prompt.txt').read_bytes()==(prior/'implementation/prompt.txt').read_bytes(),
                    'grader_identical':(base/'grader.py').read_bytes()==((baseline/f'round-{number}'/'grader.py') if (baseline/f'round-{number}').is_dir() else baseline/'grader.py').read_bytes()}
            assert all(checks.values()),checks
            controls[f'round-{number}/{level}']=checks
            shutil.copyfile(trial/'prompt.txt',trial/'original-prompt.txt')
            b.grade(base,level,'baseline')
    shutil.copyfile(ROOT/'tests/level_benchmark.py',destination/'harness-frozen.py')
    shutil.copyfile(__file__,destination/'runner-frozen.py')
    probes=[]
    inherited=read(baseline/'manifest.json').get('known_quality_probes',[])
    for name in dict.fromkeys((*PROBE_NAMES, *FOLLOWUP_PROBE_NAMES, *EFFECT_PROBE_NAMES, *SETTING_PROBE_NAMES, *inherited)):
        if (baseline/name).is_file():
            shutil.copyfile(baseline/name,destination/name);probes.append(name)
    for source in extra_probes:
        source=Path(source).resolve()
        if source.suffix!='.py' or source.name in probes or (destination/source.name).exists():
            raise ValueError('Extra probes must be distinct Python files')
        shutil.copyfile(source,destination/source.name);probes.append(source.name)
    write(destination/'controls.json',controls)
    write(destination/'manifest.json',{'status':'PREPARED','baseline_archive':str(baseline),
        'requested_model':'gpt-6-astra','requested_effort':'max','timeout_seconds':900,
        'procedure_depth':'standard','repetitions_per_level':repetitions,'baseline_repetitions_per_level':baseline_count(baseline),
        'known_quality_probes':probes,
        'orders':orders,'skill_sha256':b.digest_tree(ROOT/'skills/lean-run'),
        'budget_policy':'Same 900-second cap made visible through deadline environment; no automatic extension or early quality pass',
        'harness_sha256':hashlib.sha256((destination/'harness-frozen.py').read_bytes()).hexdigest(),
        'primary_metrics':['medium mean measured workflow seconds','medium mean uncached input','medium mean uncached input plus output'],
        'additional_metrics':['uncached input','total input plus output','cached input','all-level sum of means'],
        'quality_gate':'unchanged frozen categories, protected files, independent review, historical regressions and critical supplemental writes',
        'cache_policy':'No synthetic warmup; cache state not controlled',
        'review_integrity_policy':'All pre-review files immutable; newly created .log evidence allowed and recorded',
        'measurement_excludes':['coordinator chat','skill review','preparation','grading','cross-regressions','reporting']})
    return destination


def progress(root,number,level,phase,state):
    value={'round':number,'level':level,'phase':phase,'state':state,'unix':time.time()}
    write(root/'progress.json',value);print(json.dumps(value),flush=True)


def capture_logs(trial,phase,workspace):
    records=[];folder=trial/phase/'captured-logs'
    for line in (trial/phase/'events.jsonl').read_text().splitlines():
        event=json.loads(line);item=event.get('item',{})
        if event.get('type')!='item.completed' or item.get('type')!='command_execution':continue
        output=item.get('aggregated_output','').strip()
        try: entry=json.loads(output)
        except (ValueError,TypeError):continue
        if not isinstance(entry,dict) or not {'log','log_bytes','output_excerpt','exit_code'}<=entry.keys():continue
        path=Path(entry['log']).resolve();allowed=any(path.is_relative_to(p.resolve()) for p in (workspace,Path(tempfile.gettempdir())))
        record={'original_path':str(path),'reported_bytes':entry['log_bytes']}
        if allowed and path.suffix=='.log' and path.is_file():
            folder.mkdir(exist_ok=True);target=folder/f'{len(records)+1:03d}.log';shutil.copyfile(path,target)
            record.update(archived=str(target.relative_to(trial/phase)),sha256=hashlib.sha256(target.read_bytes()).hexdigest(),bytes=target.stat().st_size)
        else:record['unavailable_or_outside_allowed_log_roots']=True
        records.append(record)
    write(trial/phase/'captured-logs.json',records)


def run_phase(root,b,number,level,phase):
    base=root/f'round-{number}';trial=base/level
    progress(root,number,level,phase,'RUNNING')
    if not (trial/phase/'metrics.json').exists():
        if (trial/phase).exists():raise RuntimeError('Incomplete phase exists; inspect before resuming: '+str(trial/phase))
        b.run(base,level,phase,900,'gpt-6-astra','max')
    metrics=read(trial/phase/'metrics.json')
    if metrics['exit_code'] or metrics['timed_out'] or metrics['usage'] is None:
        raise RuntimeError('Measured phase incomplete; retain usage and investigate: '+str(trial/phase))
    capture_logs(trial,phase,trial/('reviewspace' if phase.startswith('review') else 'workspace'))


def cross_regressions(root,trial,level,label):
    manifest=read(root/'manifest.json')
    archives=[Path(path) for path in manifest.get('regression_archives',[manifest['baseline_archive']])]
    results=[]
    for archive_index,archive in enumerate(archives):
      for number in range(1,baseline_count(archive)+1):
        baseline=baseline_trial(archive,level,number)/'workspace'
        for name,application,tests in [('historical_tests_on_candidate',trial/'workspace',baseline),('candidate_tests_on_historical',baseline,trial/'workspace')]:
            with tempfile.TemporaryDirectory(prefix='lean-cross-regression-') as temporary:
                target=Path(temporary)
                for source in application.glob('*.py'):
                    if not source.name.startswith('test_'):shutil.copyfile(source,target/source.name)
                for source in tests.glob('test_*.py'):shutil.copyfile(source,target/source.name)
                start=time.monotonic();p=subprocess.run([sys.executable,'-B','-m','unittest','discover','-v'],cwd=target,capture_output=True,text=True,timeout=120)
                prefix='' if archive_index==0 else f'history-{archive_index}-'
                log=f'{label}-{prefix}baseline-{number}-{name}.log';(trial/log).write_text(p.stdout+p.stderr)
                results.append({'direction':name,'baseline_round':number,'baseline_archive':str(archive),
                                'exit_code':p.returncode,'seconds':round(time.monotonic()-start,3),'log':log})
    write(trial/f'{label}-cross.json',results)
    return results


def assess(root,b,number,level,index,grade_name):
    trial=root/f'round-{number}'/level;phase='review' if index==1 else f'review-{index}'
    before=read(trial/f'{phase}-hashes.json');after=b.digest_tree(trial/'reviewspace')
    changed=[k for k in before if before[k]!=after.get(k)]
    added=[k for k in after if k not in before]
    integrity={'changed_or_removed':changed,'added_logs':[k for k in added if k.endswith('.log')],
               'unexpected_additions':[k for k in added if not k.endswith('.log')]}
    write(trial/f'{phase}-integrity.json',integrity)
    review=read(trial/phase/'final.txt');grade=read(trial/grade_name)
    cross=cross_regressions(root,trial,level,phase)
    supplemental=None;probes={}
    candidate_before=b.digest_tree(trial/'workspace')
    if level=='critical':
        for name in read(root/'manifest.json').get('known_quality_probes',['supplemental_probe.py']):
            workspace=trial/'workspace'
            # A file-spec import in a copied probe must resolve sibling application modules.
            p=subprocess.run([sys.executable,'-B',str(root/name),str(workspace)],capture_output=True,text=True,
                             timeout=60,env={**os.environ,'PYTHONPATH':str(workspace)})
            try:report=json.loads(p.stdout)
            except ValueError:report=None
            log=f'{phase}-{Path(name).stem}.log';(trial/log).write_text(p.stdout+p.stderr)
            probes[name]={'exit_code':p.returncode,'report':report,'log':log,
                          'passed':p.returncode==0 and isinstance(report,dict)
                          and report.get('issue_count',report.get('failed_cases'))==0
                          and report.get('failed_cases',0)==0}
            if name=='supplemental_probe.py':supplemental=report
        write(trial/f'{phase}-known-probes.json',probes)
    blockers=[]
    if review['status']!='PASS' or review['findings']:blockers.append('independent_review')
    if grade['issues'] or grade['protected_files_changed']:blockers.append('frozen_grade_or_protected_files')
    if changed or integrity['unexpected_additions']:blockers.append('review_workspace_integrity')
    if supplemental and supplemental['issue_count']:blockers.append('critical_supplemental')
    if any(not probe['passed'] for probe in probes.values()):blockers.append('known_quality_probes')
    if candidate_before!=b.digest_tree(trial/'workspace'):blockers.append('probe_workspace_integrity')
    if any(row['exit_code'] for row in cross if row['direction']=='historical_tests_on_candidate'):blockers.append('historical_regressions')
    result={'phase':phase,'review':review,'grade':grade_name,'cross':cross,'supplemental_issue_count':None if supplemental is None else supplemental['issue_count'],
            'blockers':blockers,'review_integrity':integrity,'critical_probes':probes,'candidate_sha256':b.digest_tree(trial/'workspace')}
    write(trial/f'assessment-{index}.json',result)
    return result


def run(root):
    root=root.resolve();b=harness(root/'harness-frozen.py');manifest=read(root/'manifest.json')
    with (root/'.cohort.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        for number,order in enumerate(manifest['orders'],1):
            for level in order:
                base=root/f'round-{number}';trial=base/level
                if (trial/'result.json').exists():continue
                for index in range(1,4):
                    phase='review' if index==1 else f'review-{index}'
                    assessment_path=trial/f'assessment-{index}.json'
                    if not assessment_path.exists():
                        if index==1:
                            run_phase(root,b,number,level,'implementation')
                            grade_name='post-implementation-grade.json'
                        else:
                            repair=f'repair-{index-1}';request=read(trial/f'{repair}-request.json')
                            snapshot=trial/f'workspace-before-{repair}'
                            if not snapshot.exists():shutil.copytree(trial/'workspace',snapshot,ignore=shutil.ignore_patterns('__pycache__'))
                            brief=(f'Use lean-run at .agents/skills/lean-run/SKILL.md to continue the SAME {level} task with a bounded repair. '
                                f'CONTRACT.md and scope are unchanged. Task-wide REWORK count is {index-1}; do not reset it. '
                                'Reproduce and repair the demonstrated findings below, add meaningful regression checks, run affected and required final checks, and exercise the public interface. '
                                'Preserve existing behavior, data, triggers and unrelated work. No unrelated refactor, installs, network or extra agents. '
                                'The coordinator supplies renewed independent review afterward; report it pending. '
                                +('This is the final fix-only pass. ' if index==3 else '')+'\n\n'+json.dumps(request['findings'],indent=2)+'\n')
                            (trial/'prompt.txt').write_text(brief)
                            run_phase(root,b,number,level,repair)
                            grade_name=f'post-{repair}-grade.json'
                        if not (trial/grade_name).exists():b.grade(base,level,grade_name.removesuffix('-grade.json'))
                        if not (trial/f'{phase}-hashes.json').exists():
                            if (trial/'reviewspace').exists():(trial/'reviewspace').rename(trial/f'reviewspace-before-{phase}')
                            b.prepare_review(base,level)
                            if index==1:
                                assert (trial/'review-prompt.txt').read_bytes()==(baseline_trial(Path(manifest['baseline_archive']),level,number)/'review/prompt.txt').read_bytes()
                            else:
                                prior=trial/f'workspace-before-repair-{index-1}';pre=trial/'reviewspace/.pre-repair';pre.mkdir()
                                for source in prior.glob('*.py'):shutil.copyfile(source,pre/source.name)
                                with (trial/'review-prompt.txt').open('a') as prompt:
                                    prompt.write(f'\nRenewed independent review after REWORK {index-1}. Focus on the bounded repair delta against .pre-repair/ and original-contract regressions. Run required checks and independently verify each finding. Do not repeat unrelated broad exploration without new evidence. Prior independent findings, not author conclusions:\n'+json.dumps(request['findings'],indent=2)+'\n')
                            write(trial/f'{phase}-hashes.json',b.digest_tree(trial/'reviewspace'))
                        run_phase(root,b,number,level,phase)
                        assessment=assess(root,b,number,level,index,grade_name)
                    else:assessment=read(assessment_path)
                    if (level in manifest.get('coordinator_gate_levels', [])
                        and not (trial/f'assessment-{index}-coordinator.json').exists()):
                        progress(root,number,level,'assessment','NEEDS_COORDINATOR');return 2
                    adjudication=trial/f'assessment-{index}-adjudication.json'
                    remaining=list(assessment['blockers'])
                    if adjudication.exists():
                        approved=read(adjudication)
                        assert approved['reason'] and approved['evidence']
                        assert set(approved['noncontract_blockers']) <= {'historical_regressions','review_workspace_integrity'}
                        if 'review_workspace_integrity' in approved['noncontract_blockers']:
                            assert not assessment['review_integrity']['changed_or_removed']
                        remaining=[x for x in remaining if x not in approved['noncontract_blockers']]
                    if not remaining:
                        write(trial/'result.json',{'status':'DONE','final_assessment':index,'repair_rounds':index-1,'final_grade':assessment['grade'],
                            'final_review':phase,'initial_review_issues':len(read(trial/'review/final.txt')['findings']),'final_review_issues':0,
                            'first_pass_blockers':read(trial/'assessment-1.json')['blockers'],'adjudication':None if not adjudication.exists() else adjudication.name})
                        progress(root,number,level,'assessment','DONE');break
                    if index==3:
                        write(trial/'result.json',{'status':'FAILED','final_assessment':index,'repair_rounds':index-1,
                            'final_grade':assessment['grade'],'final_review':phase,
                            'initial_review_issues':len(read(trial/'review/final.txt')['findings']),
                            'final_review_issues':len(assessment['review']['findings']),
                            'first_pass_blockers':read(trial/'assessment-1.json')['blockers'],
                            'adjudication':None if not adjudication.exists() else adjudication.name,
                            'remaining_blockers':remaining})
                        progress(root,number,level,'assessment','FAILED');break
                    if not (trial/f'repair-{index}-request.json').exists():
                        progress(root,number,level,'assessment','NEEDS_COORDINATOR');return 2
        failed=any(read(p)['status']=='FAILED' for p in root.glob('round-*/*/result.json'))
        progress(root,len(manifest['orders']),'all','cohort','COMPLETE_WITH_FAILURES' if failed else 'COMPLETE')
        return 3 if failed else 0


def metric_summary(values):
    return {'n':len(values),'mean':statistics.mean(values),'median':statistics.median(values),
            'sample_sd':statistics.stdev(values) if len(values)>1 else None,'min':min(values),'max':max(values)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['prepare','run']);parser.add_argument('directory',type=Path);parser.add_argument('--baseline',type=Path)
    parser.add_argument('--levels',nargs='+',choices=('medium','high','critical'),default=['medium','high','critical'])
    parser.add_argument('--repetitions',type=int,choices=(1,2,3),default=3)
    parser.add_argument('--extra-probe',type=Path,action='append',default=[]);args=parser.parse_args()
    if args.command=='prepare':print(prepare(args.directory,args.baseline,args.levels,args.repetitions,args.extra_probe))
    else:raise SystemExit(run(args.directory))
