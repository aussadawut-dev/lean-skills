# Lean Skills

[English](README.md) | **ภาษาไทย**

12 skills ที่ช่วยให้ coding agent วางแผน ลงมือทำ ทดสอบ และตรวจงานได้เป็นขั้นตอน
เลือกติดตั้งทั้งชุดหรือแค่ตัวเดียวก็ได้ **ไม่ต้องติดตั้ง Lean runtime หรือมีโฟลเดอร์ `.lean`**

ใช้กับ **Codex, Claude Code และ Antigravity** ผ่าน
[Skills CLI](https://github.com/vercel-labs/skills)

## เริ่มต้นใช้งาน

เตรียม Node.js/npm เพื่อใช้คำสั่ง `npx` และติดตั้ง coding agent ที่ต้องการใช้งานก่อน
จากนั้นเลือกว่าจะติดตั้ง skills ไว้ที่ไหน:

| รูปแบบ | เหมาะกับ | ตัวเลือก |
| --- | --- | --- |
| Global | ต้องการใช้ skills ได้กับทุกโปรเจกต์ | ใส่ `-g` |
| เฉพาะโปรเจกต์ | ต้องการใช้ในโปรเจกต์ปัจจุบันเท่านั้น | ไม่ใส่ `-g` |

### ติดตั้งสำหรับทุกโปรเจกต์

```sh
npx skills add aussadawut-dev/lean-skills -g --skill '*' -a codex claude-code antigravity -y
```

### ติดตั้งเฉพาะโปรเจกต์

เปิด terminal ที่โฟลเดอร์หลักของโปรเจกต์ แล้วรัน:

```sh
npx skills add aussadawut-dev/lean-skills --skill '*' -a codex claude-code antigravity -y
```

### ติดตั้งแค่ skill เดียว

ตัวอย่าง: ติดตั้ง `lean-review` ให้ Codex เฉพาะโปรเจกต์ปัจจุบัน

```sh
npx skills add aussadawut-dev/lean-skills --skill lean-review -a codex -y
```

หากต้องการใช้ได้ทุกโปรเจกต์ ให้เพิ่ม `-g` ทุก skill ใช้แยกกันได้โดยไม่ต้องติดตั้งตัวอื่น

### ปรับคำสั่งให้ตรงกับการใช้งาน

- หลัง `-a` ใส่เฉพาะ agent ที่คุณใช้
- `--skill '*'` หมายถึงเลือกครบทั้ง 12 ตัว โดยต้องใส่เครื่องหมายคำพูดรอบ `'*'`
- `-y` คือข้ามคำถามยืนยัน หากต้องการเลือก agent ผ่านเมนู ให้ตัดทั้ง `-a` พร้อมรายชื่อ agent และ `-y` ออก
- หากต้องการดูรายการ skills โดยยังไม่ติดตั้ง ใช้คำสั่ง:

```sh
npx skills add aussadawut-dev/lean-skills --list
```

การติดตั้งแบบ global ไม่แก้ไฟล์ในโปรเจกต์ ส่วนการติดตั้งเฉพาะโปรเจกต์จะสร้างโฟลเดอร์
และลิงก์สำหรับให้ agent พบ skills เช่น `.agents/skills/` และ `.claude/skills/`
รวมถึงข้อมูลการติดตั้งตามที่ตัวติดตั้งใช้ โดยไม่เปลี่ยน global skills เดิม
ตรวจไฟล์ที่เพิ่มด้วย `git status` แล้วเลือก commit เพื่อใช้ร่วมกับทีม หรือเพิ่มใน ignore rules หากใช้ส่วนตัว

ถ้ามี skills ชื่อ `lean-*` อยู่แล้ว ให้เก็บสำเนาที่แก้เองก่อนติดตั้งทับ
skills ในโปรเจกต์อาจมีผลต่อการเลือกเวอร์ชันที่ agent เรียกใช้ด้วย
หากติดตั้งแล้วไม่พบ skills ให้โหลดใหม่หรือเริ่ม session ของ agent อีกครั้ง

## เรียกใช้ skill

บอกชื่อ skill ที่ต้องการ หรือใช้รูปแบบคำสั่งของ agent:

| Agent | ตัวอย่าง |
| --- | --- |
| Codex | `$lean-task เพิ่ม pagination พร้อม tests` |
| Claude Code | `/lean-task เพิ่ม pagination พร้อม tests` |
| Agent อื่นที่รองรับ | `ใช้ lean-task เพิ่ม pagination พร้อม tests` |

agent อาจเลือกใช้ skill จากคำอธิบายได้เองด้วย ไม่จำเป็นต้องเรียก `lean-init` ก่อน
และไม่ต้องติดตั้ง skill ตัวอื่นมาประกอบ

## เลือก skill ให้เหมาะกับงาน

| ต้องการทำอะไร | Skill |
| --- | --- |
| ทำความเข้าใจคำสั่งและแนวทางทำงานของโปรเจกต์ | [lean-init](skills/lean-init/SKILL.md) |
| ทำงานตั้งแต่กำหนดขอบเขตจนทดสอบและตรวจงานเสร็จ | [lean-task](skills/lean-task/SKILL.md) |
| ระบุว่างานครอบคลุมอะไรและจะตรวจรับอย่างไร | [lean-scope](skills/lean-scope/SKILL.md) |
| เปรียบเทียบแนวทาง พร้อมแหล่งอ้างอิงและข้อแลกเปลี่ยน | [lean-research](skills/lean-research/SKILL.md) |
| หาจุดที่ยังไม่ชัดใน requirement หรือแผนก่อนเขียนโค้ด | [lean-grill](skills/lean-grill/SKILL.md) |
| แบ่งงานให้ agent ที่มีอยู่ช่วยทำ | [lean-agents](skills/lean-agents/SKILL.md) |
| ตรวจการเปลี่ยนแปลงเพื่อหาปัญหาและผลกระทบต่อของเดิม | [lean-review](skills/lean-review/SKILL.md) |
| ตรวจหลักฐานก่อนสรุปว่างานเสร็จ | [lean-gate](skills/lean-gate/SKILL.md) |
| กำหนดความละเอียดในการทำตามขั้นตอน | [lean-effort](skills/lean-effort/SKILL.md) |
| ประเมินตัวเลือกโมเดลและเสนอปรับ configuration | [lean-model-update](skills/lean-model-update/SKILL.md) |
| เลือกหรือ clone repository ของแอปอีกตัว | [lean-target](skills/lean-target/SKILL.md) |
| อัปเดต standalone skills โดยรักษาส่วนที่แก้เองไว้ | [lean-update](skills/lean-update/SKILL.md) |

## สิ่งที่ควรรู้

skills เป็นคำแนะนำให้ agent ทำงาน ไม่ได้ติดตั้งบริการเบื้องหลัง hooks อัตโนมัติ
ระบบควบคุมสิทธิ์ หรือหลักฐาน review ที่มีลายเซ็นรับรอง การตรวจงานและทดสอบจะทำผ่าน agent
โดยใช้เครื่องมือและกติกาของโปรเจกต์คุณ

ค่าความละเอียดและ repository ที่เลือกจะอยู่ในบทสนทนา เว้นแต่คุณขอให้บันทึกไว้
การแบ่งงานต้องมีเครื่องมือเรียก agent ส่วนการประเมินโมเดลต้องมีโจทย์ เครื่องมือ และสิทธิ์ที่เหมาะสม
ชุดนี้ไม่ได้รวมทะเบียนโมเดล ชุด benchmark หรือระบบคิวงาน
หากเครื่องมือไม่พร้อม agent ควรรายงานข้อจำกัดตามจริง

การติดตั้ง skill ไม่ได้ให้สิทธิ์ commit, push, deploy, ใช้ API ที่เสียเงิน
หรือเปลี่ยนสิทธิ์ของผู้ให้บริการโดยอัตโนมัติ ยังคงใช้คำสั่งของคุณและกติกาของโปรเจกต์เป็นหลัก

## สำหรับผู้ร่วมพัฒนา

clone repository นี้ แล้วรันจากโฟลเดอร์หลักเพื่อลอง skills ที่แก้ในเครื่อง:

```sh
npx skills add ./ --skill '*' -a codex claude-code antigravity -y
```

ตรวจงานด้วย Python และ Node.js/npm:

```sh
python3 -m unittest discover -s tests -v
python3 tests/install_smoke.py
```

คำสั่งแรกใช้ standard library ของ Python ส่วน smoke test ใช้ `skills@1.7.4` ผ่าน `npx`
จึงต้องเข้าถึง registry ได้หรือมีแพ็กเกจใน cache การทดสอบครอบคลุมติดตั้งครบชุดและติดตั้งเดี่ยวทั้ง 12 ตัว
ทั้งแบบ global และเฉพาะโปรเจกต์ รวม **26 กรณี** ในโฟลเดอร์ผู้ใช้และโปรเจกต์จำลอง
ตรวจทั้งเนื้อหาและการแยกขอบเขตการติดตั้ง โดยไม่แก้ global skills จริงและไม่เรียก LLM
CI รันการตรวจทั้งสองคำสั่งนี้

การทดสอบยืนยันโครงสร้างแพ็กเกจและการติดตั้ง ส่วนพฤติกรรมของ agent ต้องตรวจเนื้อหาคำแนะนำประกอบด้วย
เมื่อแก้คู่มือ ให้ปรับภาษาอังกฤษและภาษาไทยให้ตรงกัน โดยไฟล์ skill ยังคงเป็นภาษาอังกฤษ

## สัญญาอนุญาตและที่มา

ดัดแปลงจาก [Lean Workflow Agent by ASDW](https://github.com/aussadawut-dev/lean-workflow-agent-by-asdw)
ชุดนี้มีเฉพาะ skills ไม่ได้รวมระบบบังคับใช้ workflow อัตโนมัติของต้นฉบับ

ใช้ [MIT License](LICENSE) แต่ละ skill มีไฟล์สัญญาอนุญาตของตัวเอง
กรุณาเก็บไฟล์นั้นไว้เมื่อนำ skill ไปแจกจ่ายแยกตัว
