# วิเคราะห์ log: v5.7 กับ lean-skills

ข้อเสนอคือเก็บการตรวจผลของงานที่มีความเสี่ยงให้ชัดขึ้น โดยใช้หลักฐานชุดเล็กที่แยกประเภทความผิดพลาดได้ แล้วลดการอ่านบริบทและบันทึกสถานะซ้ำ ข้อมูลรอบนี้ยังไม่รองรับการสรุปว่า v5.7 มีคุณภาพเหนือกว่าทั้งระบบ: แม้ Critical ผ่าน review ครั้งแรก แต่การตรวจข้ามชุด regression พบข้อกำหนด replay ที่หลุดไปอีก 1 สาเหตุ ซึ่งแสดงออกเป็น 2 tests ที่ fail

วิเคราะห์จาก raw logs ของการทดลองเดิม ไม่มีการเรียกโมเดลเพิ่ม การตรวจ replay เพิ่มเติมทำกับสำเนาชั่วคราวของโปรแกรมเท่านั้น ไม่ได้แก้ skills หรือ implementation ที่เก็บไว้ ผล PASS และตัวเลขในรายงานประวัติศาสตร์ยังคงเดิม การพบข้อบกพร่องภายหลังบันทึกแยกในรายงานนี้

**ตัวเลขที่วัดได้**

รวม implementation, fresh independent review และ repair/review ที่ต้องใช้จนจบ ทั้งสามระดับ:

| ตัววัด | lean-run เดิม | Native v5.7 | ความต่าง v5.7 |
| --- | ---: | ---: | ---: |
| เวลา agent | 1,999.397 วินาที | 2,329.971 วินาที | +16.53% |
| Input + output tokens | 1,752,837 | 3,713,637 | +111.86% |
| Input tokens | 1,685,766 | 3,624,365 | +1,938,599 |
| Cached input ซึ่งรวมอยู่ใน input แล้ว | 1,489,664 | 3,362,560 | +1,872,896 |
| Output tokens | 67,071 | 89,272 | +22,201 |
| Uncached input + output | 263,173 | 351,077 | +33.40% |
| Completed command events | 95 | 211 | +116 |

ใน token ที่เพิ่มทั้งหมด 1,960,800 tokens มี **98.87% เป็น input** และ **95.52% เป็น cached input** ตัวเลขนี้เป็นสัดส่วนของส่วนเพิ่ม ไม่ใช่สัดส่วนการประหยัดค่าใช้จ่าย Cached input รวมอยู่ใน input แล้ว และ reasoning output รวมอยู่ใน output แล้ว การรวมซ้ำจะทำให้ผลผิด Uncached input + output เป็นจำนวน tokens ไม่ใช่ประมาณการราคา

อ่าน [analysis.json](analysis.json) และ [phase-analysis.csv](phase-analysis.csv) เพื่อดูตัวเลขคำนวณจาก `turn.completed.usage` โดยตรง ทั้ง 22 phases ตรงกับ metrics ที่เก็บไว้

**ทำไม v5.7 ใช้บริบทมากกว่า**

v5.7 ที่ commit `16ecbec10ea8a2f7c43bf4eca61f796ef6d2d019` ใช้ `lean-task` เป็น controller พร้อม native skills/policies/runtime และโหมด tracker/direct ส่วน reference ใช้ standalone `lean-run` นี่จึงเป็นการเทียบ workflow ที่ติดตั้งครบกับ skill ที่ทำงานได้เอง โดยมี coordinator จัด fresh review ให้ทั้งคู่

- จาก 211 command events ของ v5.7 มี 111 events ที่เรียก native CLI อย่างน้อย 115 invocations; ในจำนวนนี้มี 17 events ที่เป็นการขอ help ล้วน ตัวนับเป็นขอบล่าง เพราะไม่นับ CLI ที่เรียกผ่าน Python แบบ dynamic
- กลุ่ม `progress`, `tracker`, `mode` รวมอย่างน้อย 69 invocations และมี file-change events ของ tracker 17 ครั้ง นอกจากนี้ยังมี evidence, gate, contract, models และ test commands หลายส่วนทำหน้าที่ตรวจหลักฐานที่มีประโยชน์ จึงไม่ควรถือทุกคำสั่งเป็นงานที่ตัดออกได้
- การค้นหา command ที่อ่าน instruction/contract พบ 35 events / output 492,225 ตัวอักษรใน v5.7 เทียบกับ 21 / 154,728 ใน lean-run เดิม ตัวนับนี้เป็น heuristic และบาง command อ่าน requirements/source ผสมกัน ตัวอักษรไม่ใช่ tokens
- ใน Critical implementation เพียงช่วงต้นมีการอ่าน controller/CONTRACT/PROJECT ประมาณ 6.7k ตัวอักษร, AGENTS/README 11.2k, scope/grill/workflow/testing 19.6k และ contracts/review/quality/gate/review อีก 38.6k ก่อนมีการอ่านบางส่วนซ้ำ ดู [raw log](</Users/x10/Workspace/Me/Github/lean-workflow-agent-by-asdw/docs/benchmarks/2026-11-03-three-level-v5.7/critical/implementation/events.jsonl:6>) และ command inventory สำหรับคำสั่งแต่ละรายการ

หลักฐานเหล่านี้สอดคล้องกับบริบทที่ใหญ่และมีรอบ tool มากขึ้น จึงมี input และ cached prefix ถูกนับสะสมมากขึ้น แต่ usage ที่มีอยู่แยกได้เพียงระดับ phase ไม่สามารถแจกแจงว่าแต่ละ CLI หรือการอ่านไฟล์ใช้กี่ tokens ได้

ขนาด tool output รวมทั้งหมดของ v5.7 อยู่ที่ 673,131 ตัวอักษร ซึ่งต่ำกว่า lean-run เดิม 707,247 เล็กน้อย ดังนั้นจำนวนอักษร output ใหม่เพียงตัวเดียวอธิบาย token ทั้งหมดไม่ได้ ลำดับการอ่าน ชนิดบริบท และจำนวนรอบมีส่วนร่วมด้วย ดู [command-inventory.json](command-inventory.json) ซึ่งระบุ path และเลขบรรทัดของ raw log ทุก command

มีค่าใช้จ่ายจากรูปแบบเอกสาร เช่น high reviewer ต้องแก้ native assessment ที่รูปแบบยังไม่ถูกต้องก่อนบันทึก receipt ได้ เหตุการณ์เหล่านี้รวมอยู่ในเวลา/tokens แต่แยกจาก application bugs ตามหน่วยนับเดิม

**ทำไม Critical ไม่ต้องแก้ F1 ในรอบ v5.7**

| Critical | lean-run เดิม | v5.7 |
| --- | ---: | ---: |
| Implementation + review ครั้งแรก | 799.062 วินาที / 654,045 tokens | 1,056.525 วินาที / 1,414,463 tokens |
| Repair + renewed review | 340.779 วินาที / 488,008 tokens | ไม่มี |
| รวม | 1,139.841 วินาที / 1,142,053 tokens | 1,056.525 วินาที / 1,414,463 tokens |

v5.7 ใช้เวลาเพิ่มก่อนจบ review ครั้งแรกประมาณ 4:17 นาที แต่เลี่ยง repair/review ที่ reference ใช้อีก 5:41 นาที จึงจบ Critical เร็วกว่า 7.31% โดยยังใช้ tokens มากกว่า 23.85%

ความต่างของโปรแกรมที่อธิบาย F1 ได้ตรงที่สุดคือ v5.7 ตรวจว่าการเขียนแต่ละรายการเกิดผลจริงผ่าน `_write_one()` และ `rowcount != 1` ก่อนยอมให้ transaction สำเร็จ ดู [vault.py](</Users/x10/Workspace/Me/Github/lean-workflow-agent-by-asdw/docs/benchmarks/2026-11-03-three-level-v5.7/critical/workspace-view/vault.py:36>) จึงตรวจพบทั้ง SQLite exception และ trigger ที่ใช้ `RAISE(IGNORE)` เพื่อข้าม write โดยไม่โยน exception

ลำดับใน [implementation log](</Users/x10/Workspace/Me/Github/lean-workflow-agent-by-asdw/docs/benchmarks/2026-11-03-three-level-v5.7/critical/implementation/events.jsonl:58>) ยืนยันว่ามี application patch ครั้งเดียวที่บรรทัด 58 หลังจากนั้น 34 regression tests ผ่าน ผู้เขียนระบุช่องว่างเรื่อง silent ignore กับ failure ที่ COMMIT ที่บรรทัด 66 เพิ่มเฉพาะ tests ที่บรรทัด 68 และ 13 atomicity tests ผ่านที่บรรทัด 70 ก่อนส่ง review ไม่ได้รอให้ reviewer พบ F1 แล้วจึงแก้โปรแกรม

ชุด [atomicity tests](</Users/x10/Workspace/Me/Github/lean-workflow-agent-by-asdw/docs/benchmarks/2026-11-03-three-level-v5.7/critical/workspace-view/test_regressions.py:290>) ครอบคลุม ignored debit, credit, receipt, audit และ late commit failure ส่วน [coverage record](</Users/x10/Workspace/Me/Github/lean-workflow-agent-by-asdw/docs/benchmarks/2026-11-03-three-level-v5.7/critical/workspace-view/docs/tracking/TCK001.md:55>) เชื่อม acceptance เข้ากับ checks ที่รัน

lean-run เดิมมี transaction และ tests ที่ผ่าน 29 ข้อ แต่ reviewer ทดสอบ suppressed writes แล้วพบกรณี credit โดยไม่มี debit, ไม่มี audit และไม่มี receipt จน replay หักเงินซ้ำ ดู [F1 และหลักฐาน](</Users/x10/Workspace/Me/Github/lean-skills/tests/results/2026-11-03-level-benchmark/critical/review/events.jsonl:40>) ข้อดีที่ควรนำมาใช้คือการตรวจผลที่จำเป็นและ failure ที่ไม่โยน exception รวมถึงการหา failure class ที่ยังขาดอยู่ จำนวน tests 40 เทียบกับ 29 เพียงอย่างเดียวไม่ได้พิสูจน์ coverage

ทั้งคู่ขอ model/effort `gpt-6-astra / max` และ standard procedure depth เหมือนกัน v5.7 ระบุ quality `VERY_HIGH` ขณะที่บริบท/นโยบายทั้งชุดต่างกัน จึงยังระบุไม่ได้ว่าประโยคใดใน skill เป็นเหตุให้โมเดลเลือก guard นี้ หรือว่า receipt/tracker ทำให้ได้คุณภาพดังกล่าว

**PASS ครั้งแรกมีข้อบกพร่องที่ review ไม่พบ**

เมื่อตรวจ source พบว่า v5.7 คืน cached receipt ที่ [vault.py:68](</Users/x10/Workspace/Me/Github/lean-workflow-agent-by-asdw/docs/benchmarks/2026-11-03-three-level-v5.7/critical/reviewspace-view/vault.py:68>) ก่อนตรวจว่าบัญชี source/target ยังมีอยู่ที่บรรทัด 70–71 ขณะที่ [สัญญาโจทย์](</Users/x10/Workspace/Me/Github/lean-skills/tests/results/2026-11-03-level-benchmark/critical/initial/CONTRACT.md:10>) กำหนด existing source/target และ generic error สำหรับบัญชีที่ไม่มี/เข้าถึงไม่ได้

นำ regression เดิมทั้งสองข้อมาใช้โดยไม่เปลี่ยน assertion: โอนสำเร็จ → ลบ source หรือ target ใน fixture → replay คำขอเดิม → คาดว่า ValueError เหมือนการอ่านบัญชีที่ไม่มี และไม่มี mutation ทำกับสำเนาชั่วคราวของแต่ละ implementation:

| Final implementation | replay หลังลบ source | replay หลังลบ target |
| --- | --- | --- |
| v5.7 | FAIL: ไม่ raise ValueError | FAIL: ไม่ raise ValueError |
| lean-run เดิมหลัง repair | PASS | PASS |
| lean-run optimized หลัง repair | PASS | PASS |

ดู [ผลพร้อม hashes และ command](posthoc-cross-regression.json), [v5.7 failure log](v57-replay-check.log), [original pass](lean_original_final-replay-check.log), [optimized pass](lean_optimized_final-replay-check.log) และ [tests เดิม](</Users/x10/Workspace/Me/Github/lean-skills/tests/results/2026-11-03-level-benchmark/critical/workspace/test_regressions.py:260>) นับเป็น **1 สาเหตุ / 2 manifestations** แยกจาก issue count ใน review ประวัติศาสตร์ ยังไม่ได้ประเมินเวอร์ชันเหล่านี้ครบทุก failure class จึงไม่ควรใช้ตัวเลขนี้เป็นยอด bugs ทั้งหมด

ข้อสรุปนี้อิง contract เฉพาะโจทย์นี้ ไม่ได้กำหนดว่าทุกระบบต้องปฏิเสธการอ่าน receipt หลังบัญชีถูกลบ และ replay ที่ถูกต้องไม่ควรถูกนำไปเช็ก insufficient funds ซ้ำจนปฏิเสธคำขอเดิมหลังการโอนทำให้เงินลดลง ต้องแยก applicable preconditions ออกจากเงื่อนไขที่ใช้เฉพาะการทำรายการใหม่ กรณีที่พบไม่ได้พิสูจน์การเปิดเผยข้อมูลข้าม tenant หรือการเขียนเงินซ้ำ

ดังนั้นสถานะที่ตรงหลักฐานคือ “v5.7 ไม่มี application finding ใน first review และผ่าน checks ที่รันในรอบนั้น แต่มี contract gap ที่พบภายหลัง” Fresh independent review และ native receipt/gate ยังมีประโยชน์ แต่ไม่ได้รับประกันว่าจะพบทุกข้อบกพร่อง

**จุดที่เสนอให้ปรับ lean-skills เรียงตามความคุ้มค่า**

| ลำดับ | จุดปรับ | ข้อเสนอ | วิธีจำกัดเวลา/tokens |
| --- | --- | --- | --- |
| P0 | `lean-run`, standalone `lean-task` | สำหรับ consequential state changes ให้ระบุผลที่ต้องเกิด, state ที่ต้องคงไว้เมื่อผิดพลาด, silent/partial effect เมื่อ API ทำได้, failure ตอน finalize/commit และ preconditions ที่ยังใช้กับ replay/cache/early return | เช็กเฉพาะที่เข้ากับ contract/implementation ใช้ table-driven probes แยก failure classes และ reuse coverage ที่มีอยู่ |
| P0 | `lean-review` | reviewer หาเงื่อนไขที่ coverage ยังไม่แสดง โดยไล่ return paths/shortcut และตรวจผลจริงทั้ง success/failure พร้อม positive preservation case ที่ตรงกัน | อ่าน source/diff ปัจจุบันและเลือก distinguishing probes ไม่เพิ่ม exhaustive/random sweeps โดยไม่มีสมมติฐาน ไม่ลด fresh independence |
| P0 | regression bank ของ benchmark | เก็บทั้ง silent-write และ replay-precondition regressions พร้อม commit failure, duplicate execution และ valid replay หลัง funds ลดลง แล้วทดสอบข้าม implementations | รัน deterministic tests ราคาถูกก่อนใช้โมเดล เก็บ bank นอก skill prompt และแยก oracle รุ่นใหม่จาก frozen grader เดิม |
| P1 | `lean-gate` และ handoff | ใช้ evidence map สั้น ๆ ที่ผูก acceptance กับ check/result ของเนื้อหาปัจจุบัน แสดงช่องว่างที่ยังไม่มีหลักฐาน และแยก recorded PASS จากผลที่ตรวจใหม่ | ใช้บันทึกใน chat หรือ project record ที่มีอยู่ ไม่สร้าง runtime/tracker/receipt ใหม่เป็นเงื่อนไข เรียก required commands และ reuse ผลที่ inputs/environment ไม่เปลี่ยนตามกฎโครงการ |
| P1 | ทุก entrypoint ที่เกี่ยวข้อง | เก็บบริบทที่ช่วยตัดสินใจและข้อกำหนดสำคัญใน entrypoint แล้วอ่านรายละเอียดตาม risk/งาน | รักษา selective references, bounded logs และ batch reads; อย่าคัดลอก native policy ทั้งชุดของ v5.7 มาโหลดทุกงาน |

ตัวอย่างข้อความสั้นสำหรับพิจารณารวมในขั้น implement/review ของ skill ที่ทำงานเดี่ยวได้ (เป็นข้อเสนอ ยังไม่แก้ SKILL.md):

> For consequential state changes, map each requirement to observable effects and a focused check. Cover applicable silent or partial writes, late failures, and replay/cache/early-return preconditions; preserve valid retries and replays. Reuse existing coverage and batch probes by distinct failure class. A reviewer inspects current source and targets uncovered guarantees. Record expected versus observed state, limits and evidence; test counts or a prior PASS alone do not establish coverage.

อาจใช้หลักฐานบรรทัดเดียวต่อ guarantee เช่น `requirement | failure/shortcut | expected state | probe/result` โดยไม่บังคับไฟล์หรือ schema ใหม่ หลักการ SQLite `rowcount == 1` เป็นตัวอย่างของโจทย์นี้ ต้องเลือกวิธียืนยันผลที่ตรง API/contract ของแต่ละระบบ ไม่บังคับให้ทุก write ในทุกระบบมีหนึ่งแถวเสมอ

**สิ่งที่มีอยู่แล้วและสิ่งที่ยังไม่ได้วัด**

optimized benchmark ที่ freeze entrypoint 8,819 ตัวอักษรลด total tokens 9.21% และเวลา 3.02% แต่ uncached input + output เพิ่ม 17.23% และ Critical ยังพบ F1 เดิมก่อน repair ดู [รายงาน before/after](</Users/x10/Workspace/Me/Github/lean-skills/tests/results/2026-11-03-lean-run-optimized/README.md:3>) ผลนี้สนับสนุนให้ทำ semantic coverage ควบคู่กับการย่อบริบท ยังยืนยันการลดค่าใช้จ่ายหรือความเร็วที่ทำซ้ำได้ไม่ได้

working tree ที่อ่านระหว่างวิเคราะห์เปลี่ยนต่อจาก snapshot นั้นแล้ว: `lean-run` มี requirement mapping, การตรวจ partial/no-effect writes, bounded review probes และ bundled check runner เพิ่มขึ้น ข้อเสนอด้าน silent write/จำกัด logs จึงมีบางส่วนอยู่ใน entrypoint ปัจจุบันแล้ว ส่วนที่ยังควรเน้นคือ replay/early return, การทำให้ standalone companions ให้แนวทางสอดคล้องกัน และ regression bank ดู [current skill identity](current-skill-identity.json) สำหรับเวลาที่ตรวจและ hashes ผล benchmark ของ snapshot 8,819 ตัวอักษรไม่ใช่ผลทดสอบ working tree ล่าสุด

**การวัดผลหลังนำข้อเสนอไปใช้**

เริ่มจาก deterministic regression bank ที่รักษา positive behavior และตรวจข้ามเวอร์ชัน จากนั้นค่อยทำ paired A/B ระหว่าง current optimized snapshot ที่ freeze ใหม่กับ candidate ที่เพิ่ม semantic checks ใช้ fixtures, contract, model/effort, quality floor, fresh review และเงื่อนไขรันเดียวกัน สลับลำดับและทำหลายซ้ำ เช่นอย่างน้อย 3 ครั้งต่อระดับเพื่อเริ่มเห็นความแปรปรวน

วัด end-to-end time รวม repair, total/cached/uncached input/output แยกกัน, first-review findings, findings ที่ oracle พบแต่ review ไม่พบ และ unresolved root causes หลังจบ รายงาน median กับช่วงค่าที่พบ เกณฑ์คุณภาพควรเป็น known regressions ผ่านและ valid behavior คงอยู่ ส่วนเกณฑ์ประหยัดควรดูทั้งเวลาจนจบและ uncached/output ภายใต้ coverage เดียวกัน ยังไม่กำหนดเปอร์เซ็นต์ประหยัดที่ข้อมูลไม่รองรับ และไม่ได้เปิด model benchmark รอบใหม่ในงานวิเคราะห์นี้

**ขอบเขตและการตรวจหลักฐาน**

การทดลองเดิมมีเพียง 1 ครั้งต่อระดับ/เวอร์ชัน ไม่ได้ reset caches หรือควบคุม server load รวมเฉพาะ CLI implementation/review/repair; ไม่รวม coordinator/setup/grading/reporting จึงไม่ใช่เวลาและ tokens ของ chat ทั้งหมด การวิเคราะห์ normal v5.7 overhead ใช้เฉพาะ corrected trials ไม่รวม pilot ที่ setup ผิด รายละเอียดวิธีรันอยู่ใน [รายงาน v5.7](</Users/x10/Workspace/Me/Github/lean-workflow-agent-by-asdw/docs/benchmarks/2026-11-03-three-level-v5.7/README.md:37>)

ตรวจ SHA-256 ของ archive ทั้งสามชุดกับ manifest เดิมครบ 855 files: ไม่มีไฟล์เปลี่ยนหรือหาย ดู [archive-integrity.json](archive-integrity.json) และ [ผลตรวจหลักฐาน](validation.json) การคำนวณตัวเลขซ้ำทำได้ด้วย `python3 -B tests/results/2026-11-03-v57-log-analysis/analyze_logs.py` จาก repository นี้ เป็นการอ่าน logs แบบ offline ไม่มีการเรียกโมเดล [source-identities.json](source-identities.json) เก็บ hashes ของ raw logs ทั้ง 22 phases และ [analyze_logs.py](analyze_logs.py) แสดงวิธีนับและข้อจำกัดทั้งหมด
