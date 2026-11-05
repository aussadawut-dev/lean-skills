"""Reattach the deadline and harvest evidence from the orphaned CLI phase."""
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import time

root = Path(__file__).resolve().parent
phase = root / 'round-3/critical/repair-1'
lock = (root / '.cohort.lock').open('a')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
metrics_path = phase / 'metrics.json'
if metrics_path.exists():
    raise SystemExit('Metrics already exist')
running = json.loads((phase / 'running.json').read_text())
pid = running['pid']
started = running['started_unix']
deadline = started + json.loads((root / 'manifest.json').read_text())['timeout_seconds']
interval = 0.1

def still_running():
    result = subprocess.run(['ps', '-p', str(pid), '-o', 'state=', '-o', 'command='],
                            text=True, capture_output=True)
    status = result.stdout.strip()
    if not status or status.startswith('Z'):
        return False
    if str(phase / 'final.txt') not in status or 'codex' not in status:
        raise RuntimeError('PID does not match the archived CLI command')
    return True

observed_live = still_running()
timed_out = False
while still_running():
    if time.time() >= deadline:
        os.killpg(pid, signal.SIGTERM)
        timed_out = True
        kill_deadline = time.monotonic() + 10
        while still_running() and time.monotonic() < kill_deadline:
            time.sleep(interval)
        if still_running():
            os.killpg(pid, signal.SIGKILL)
        while still_running():
            time.sleep(interval)
        break
    time.sleep(interval)
ended = time.time()

events_path = phase / 'events.jsonl'
events = []
for line in events_path.read_text().splitlines():
    try:
        events.append(json.loads(line))
    except json.JSONDecodeError:
        continue
usages = [event['usage'] for event in events if event.get('type') == 'turn.completed' and 'usage' in event]
usage = {key: sum(part.get(key, 0) for part in usages) for key in set().union(*usages)} if usages else None
final_path = phase / 'final.txt'
complete = bool(usages and final_path.is_file() and final_path.stat().st_size)
recovery = {
    'phase': str(phase.relative_to(root)),
    'cause': 'Parent coordinator exited during a chat interruption. Existing CLI process was adopted by launchd.',
    'original_pid': pid, 'orphan_observed_live': observed_live, 'poll_interval_seconds': interval,
    'original_deadline_unix': deadline, 'terminal_observed_unix': ended,
    'raw_exit_code_recoverable': False, 'completed_turn_and_final_artifact': complete,
    'elapsed_source': 'Original recorded launch through first observed CLI exit, polled at 0.1 second intervals',
    'relaunched': False
}
(root / 'interruption-recovery.json').write_text(json.dumps(recovery, indent=2) + '\n')
if not observed_live or (not timed_out and not complete):
    raise SystemExit('Cannot establish full phase termination from live observation and artifacts')
metrics = {
    'level': 'critical', 'phase': 'repair-1', 'started_unix': started,
    'elapsed_seconds': round(ended - started, 3), 'exit_code': None, 'timed_out': timed_out,
    'usage': usage, 'requested_model': 'gpt-6-astra', 'requested_effort': 'max',
    'model_identity_evidence': 'requested CLI controls; backend identity not independently attested',
    'completed_turns': len(usages), 'command': running['command'],
    'command_count': sum(event.get('type') == 'item.completed' and
                         event.get('item', {}).get('type') == 'command_execution' for event in events),
    'event_types': sorted({event.get('type', 'unknown') for event in events}),
    'measurement_recovery': '../interruption-recovery.json'
}
if usage:
    metrics['total_tokens'] = usage.get('input_tokens', 0) + usage.get('output_tokens', 0)
    metrics['uncached_input_tokens'] = usage.get('input_tokens', 0) - usage.get('cached_input_tokens', 0)
metrics_path.write_text(json.dumps(metrics, indent=2) + '\n')
print(json.dumps(recovery), flush=True)
