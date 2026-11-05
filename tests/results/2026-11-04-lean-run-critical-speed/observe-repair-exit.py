"""Read the original repair process exit status through Darwin EVFILT_PROC."""
import json, os, select, subprocess, time
from pathlib import Path

root = Path(__file__).resolve().parent
phase = root / 'round-3/critical/repair-1'
running = json.loads((phase / 'running.json').read_text())
pid = running['pid']
command = subprocess.check_output(['ps', '-p', str(pid), '-o', 'command='], text=True)
if str(phase / 'final.txt') not in command:
    raise SystemExit('Original CLI process no longer exists')
queue = select.kqueue()
try:
    flags = select.KQ_NOTE_EXIT | 0x04000000  # Darwin NOTE_EXITSTATUS
    event = select.kevent(pid, filter=select.KQ_FILTER_PROC,
                          flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE, fflags=flags)
    events = queue.control([event], 1, 900)
    observed = time.time()
finally:
    queue.close()
if len(events) != 1 or not events[0].fflags & 0x04000000:
    raise SystemExit('Darwin did not return a process exit status')
data = {'pid':pid, 'raw_wait_status':events[0].data,
        'exit_code':os.waitstatus_to_exitcode(events[0].data), 'observed_exit_unix':observed}
(root / 'recovered-exit-status.json').write_text(json.dumps(data, indent=2) + '\n')
print(json.dumps(data))
