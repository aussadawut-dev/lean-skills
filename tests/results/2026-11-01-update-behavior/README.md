# lean-run and lean-update behavioral trials

Fresh Codex agents ran the new scenarios in disposable local fixtures. The
coordinator independently compared final artifacts and hashes. No network,
production installation or real publication was used. Fixture instructions
and isolated paths were the boundaries; this was not an OS sandbox. Agent
messages are summarized here, not a complete raw tool transcript. Model and
effort were inherited; backend identity and settings were not exposed.

| Case | Result | Observed evidence |
| --- | --- | --- |
| lean-run 11 | PASS | Fixed CLI example, ran its test and example, delivered a byte-identical `app.py` to local simulated destination. |
| lean-run 12 | PASS | Reproduced invalid input and proposed fix; application files matched the initial snapshot. |
| U1 collection | PASS, bounded | With offline Skills CLI 1.7.4, updated `lean-init`, added `lean-instructions`, preserved unrelated skill, verified links and backup. A final rerun on the amended skill retained the pinned snapshot and revision record. |
| U2 named | PASS | Updated only `lean-init`; missing `lean-instructions` stayed absent; candidate bytes, links and backup verified. |
| U3 conflict | PASS | Preserved customized `lean-init` byte-for-byte, reported conflict, installed independent missing skill; overall update remained partial. |
| U4 preview | PASS, limited | Reported additions and update; initial and final project hashes matched. Installer capability and metadata could not be confirmed in this first fixture. |
| U5 scope | PASS, limited | Agent asked for a scope before mutation; project hashes matched. Global fixture initial hashes were not captured in that run; the generator has since been fixed to record them. |

The first U1–U3 fixtures lacked an offline installer: U2/U3 were BLOCKED, and U1
used manual copies without installer metadata. Those were not counted as full
passes. The fixture generator was amended to accept a copied local CLI and the
three cases were rerun in fresh fixtures. The CLI recorded local snapshot paths
in `skills-lock.json`, not Git revision IDs. `lean-update` was amended to require
a usable retained source and recorded revision; U1 was rerun against that final
candidate. U2–U5 were run against the preceding candidate, before that narrow
source-retention amendment; they were not rerun after it.

Final `lean-update/SKILL.md` SHA-256:
`78c2635d6976075c441b99d8b9077ece2d265e2a3e44fa294812e355dc5c879f`.
The final U1 fixture pinned revision `6206119eeeae41d4c5ad8531e8eea1b076de3515`
and retained a source snapshot and `pinned-source.json` within the fixture.
Because the fixture is under `/tmp`, source longevity is demonstrated only during
the trial; long-term production retention and real upstream updates are not
proven. Temporary fixtures are not durable archived evidence. The standalone
fixture structure tests and local skill validator were also run separately.
