# `scripts/contextual_prefix.py` — 상세 코드 설계

> 목적: 온톨로지 엔트리 + 법률문서 청크에 contextual prefix를 배치 생성하는 스크립트
> 패턴 원본: `scripts/enrich_aliases.py`

---

## 1. 전체 구조

```python
#!/usr/bin/env python3
"""
Contextual Retrieval 맥락 접두어(prefix) 배치 생성 스크립트

각 온톨로지 엔트리 / 법률문서 청크에 대해 Claude Sonnet을 사용하여
검색 맥락 접두어를 생성하고, 별도 JSON 파일에 저장한다.

실행 모드:
  --once                   미처리 배치 1개만 처리 후 종료 (cron용)
  --all                    전체 배치 연속 처리
  --status                 진행률 출력
  --collection {ontology,legal,all}  대상 컬렉션 (기본: all)
  --gen-summaries          브랜치 요약만 생성 (사전 작업, 1회)

체크포인트: ontology_data/ctx_checkpoints/{collection}_{batch_num}.json
출력:
  - ontology_data/contextual_prefixes/{branch}.json
  - data/domain_ontology/parsed/contextual_prefixes/2025_housing_tax_v2.json
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# ─────────────────────────── 상수 ───────────────────────────

PROJECT_ROOT   = Path("/home/gon/ws/rag")
ENTRIES_DIR    = PROJECT_ROOT / "ontology_data" / "entries"
LEGAL_DOC      = PROJECT_ROOT / "data" / "domain_ontology" / "parsed" / "2025_housing_tax_v2.json"

PREFIX_DIR_ONTO  = PROJECT_ROOT / "ontology_data" / "contextual_prefixes"
PREFIX_DIR_LEGAL = PROJECT_ROOT / "data" / "domain_ontology" / "parsed" / "contextual_prefixes"
CHECKPOINT_DIR   = PROJECT_ROOT / "ontology_data" / "ctx_checkpoints"
SUMMARIES_FILE   = PREFIX_DIR_ONTO / "_branch_summaries.json"

CLAUDE_BIN     = "/home/gon/bin/claude-code"
MODEL          = "sonnet"
BATCH_SIZE_ONTO  = 15   # 온톨로지 15개/배치
BATCH_SIZE_LEGAL = 8    # 법률문서 8개/배치
```

---

## 2. 프롬프트 생성 함수

### 2-1. 브랜치 요약 프롬프트

```python
def build_hierarchy_tree(entries: list[dict]) -> str:
    """엔트리 목록에서 term 계층 구조를 트리 문자열로 생성."""
    # level별 정렬 후 parent-child 관계로 트리 텍스트 구성
    # 결과 예시:
    # 세금
    #   ├ 취득세
    #   │  ├ 취득세 중과
    #   │  └ 취득세 감면
    #   ├ 양도소득세
    #   ...

    by_parent = {}
    for e in entries:
        pid = e.get("parent_id", "")
        by_parent.setdefault(pid, []).append(e)

    lines = []
    def render(parent_id: str, indent: int):
        children = sorted(by_parent.get(parent_id, []), key=lambda x: x["term"])
        for i, child in enumerate(children):
            prefix = "  " * indent + ("└ " if i == len(children) - 1 else "├ ")
            lines.append(f"{prefix}{child['term']}")
            render(child["id"], indent + 1)

    # 루트 (level 1)
    roots = [e for e in entries if e.get("level", 1) == 1]
    for root in sorted(roots, key=lambda x: x["term"]):
        lines.append(root["term"])
        render(root["id"], 1)

    return "\n".join(lines[:80])  # 최대 80줄 (너무 깊은 트리 방지)


SUMMARY_PROMPT_TEMPLATE = """당신은 대한민국 부동산 RAG 시스템 전문가입니다.

아래는 부동산 온톨로지의 '{branch_korean}' 분야에 포함된 용어 계층 구조입니다.
이 분야가 다루는 범위와 핵심 개념을 2~3문장으로 요약하세요.
일반인이 어떤 상황에서 이 분야의 용어를 검색하게 되는지도 포함하세요.

<hierarchy>
{hierarchy_tree}
</hierarchy>

요약만 반환하세요 (다른 텍스트 없이)."""

# 브랜치명 한국어 매핑
BRANCH_KO = {
    "tax": "세금", "auction": "경매", "contract": "계약/거래",
    "land": "토지/용도지역", "loan": "대출/금융", "rental": "임대차",
    "reconstruction": "재건축/재개발", "registration": "등기",
    "regulation": "규제/정책", "subscription": "청약/분양",
}
```

### 2-2. 온톨로지 엔트리 prefix 프롬프트

```python
ONTOLOGY_PREFIX_PROMPT = """당신은 대한민국 부동산 RAG 시스템의 검색 품질 개선 전문가입니다.

각 온톨로지 항목에 대해 **검색 맥락 접두어(contextual prefix)** 를 1~2문장으로 생성하세요.
이 접두어는 임베딩 벡터 생성 시 항목 텍스트 앞에 붙어서,
사용자의 추상적 질의("집 살 때 세금")가 정확한 전문 용어("취득세")를
찾을 수 있도록 의미적 다리 역할을 합니다.

## 접두어 작성 기준
1. 해당 항목이 속한 분야(branch)와 상위 카테고리와의 관계를 명시
2. 일반인이 이 용어를 찾게 되는 실제 상황/맥락을 포함
3. 관련된 핵심 동의어나 상위 개념을 자연스럽게 포함
4. 한국어 기준 75~150자 (영문 50~100 토큰 상당)

## 절대 하지 말 것
- 용어의 정의를 반복 (description과 중복 금지)
- "이 항목은..." 같은 메타 표현으로 시작
- aliases를 나열

<branch_context>
분야: {branch_name} ({branch_korean})
분야 요약: {branch_summary}
상위 계층:
{hierarchy_excerpt}
</branch_context>

아래 각 항목에 대해 contextual_prefix를 생성하세요.

{entries_block}

JSON 배열로만 응답하세요:
[
  {{"id": "항목_id", "contextual_prefix": "생성된 접두어"}},
  ...
]"""


def make_ontology_prompt(entries: list[dict], branch: str,
                          summaries: dict, all_entries: list[dict]) -> str:
    """온톨로지 배치에 대한 prefix 생성 프롬프트 조립."""
    branch_ko = BRANCH_KO.get(branch, branch)
    branch_summary = summaries.get(branch, f"{branch_ko} 분야의 부동산 용어")

    # 배치 항목의 상위 계층 추출
    parent_ids = set(e.get("parent_id", "") for e in entries)
    hierarchy_entries = [e for e in all_entries if e["id"] in parent_ids or e.get("level", 1) <= 2]
    hierarchy_excerpt = build_hierarchy_tree(hierarchy_entries)

    # 엔트리 블록 구성
    items = ""
    for e in entries:
        items += f"\n[{e['id']}]\n"
        items += f"  용어: {e['term']}\n"
        items += f"  카테고리: {e.get('category_path', branch_ko)}\n"
        items += f"  설명 (발췌): {e.get('description', '')[:200]}\n"

    return ONTOLOGY_PREFIX_PROMPT.format(
        branch_name=branch,
        branch_korean=branch_ko,
        branch_summary=branch_summary,
        hierarchy_excerpt=hierarchy_excerpt,
        entries_block=items,
    )
```

### 2-3. 법률문서 청크 prefix 프롬프트

```python
LEGAL_PREFIX_PROMPT = """당신은 대한민국 부동산 세금 법령 해설서 검색 개선 전문가입니다.

각 법률 문서 청크에 대해 **검색 맥락 접두어(contextual prefix)** 를 1~2문장으로 생성하세요.
이 접두어는 임베딩 벡터 생성 시 청크 앞에 붙어서,
해당 청크가 전체 문서에서 어떤 맥락에 위치하는지를 알려주는 역할을 합니다.

## 접두어 작성 기준
1. 이 청크가 "2025 주택과 세금"의 어느 부분(편/장/절)에 해당하는지 명시
2. 다루는 세금 종류, 적용 대상, 핵심 조건을 간결하게 포함
3. 일반인이 이 내용을 찾게 되는 질문 맥락을 반영
4. 한국어 기준 75~150자

<document_context>
문서: 2025 주택과 세금 (국세청·행정안전부, 2025)
현재 위치: {part_title} > {chapter_title} > {section_title}
</document_context>

<surrounding>
[이전 청크 요약] {prev_excerpt}
[다음 청크 요약] {next_excerpt}
</surrounding>

아래 각 청크에 대해 contextual_prefix를 생성하세요.

{chunks_block}

JSON 배열로만 응답하세요:
[
  {{"chunk_id": "청크_id", "contextual_prefix": "생성된 접두어"}},
  ...
]"""


def make_legal_prompt(chunks: list[dict], all_chunks: list[dict],
                       chunk_indices: list[int]) -> str:
    """법률문서 배치에 대한 prefix 생성 프롬프트 조립."""
    # 첫 번째 청크의 hierarchy로 document_context 구성
    first = chunks[0]
    hier = first.get("hierarchy", {})
    part_title = hier.get("part_title", "")
    chapter_title = hier.get("chapter_title", "")
    section_title = hier.get("section_title", "")

    # 인접 청크 발췌
    first_idx = chunk_indices[0]
    prev_excerpt = ""
    next_excerpt = ""
    if first_idx > 0:
        prev_prose = all_chunks[first_idx - 1].get("content", {}).get("prose", "")
        prev_excerpt = prev_prose[:150] + "..." if len(prev_prose) > 150 else prev_prose
    last_idx = chunk_indices[-1]
    if last_idx < len(all_chunks) - 1:
        next_prose = all_chunks[last_idx + 1].get("content", {}).get("prose", "")
        next_excerpt = next_prose[:150] + "..." if len(next_prose) > 150 else next_prose

    # 청크 블록 구성
    items = ""
    for c in chunks:
        prose = c.get("content", {}).get("prose", "")
        tables = c.get("content", {}).get("tables", [])
        hyde = c.get("retrieval", {}).get("hyde_questions", [])

        items += f"\n[{c['chunk_id']}]\n"
        items += f"  본문 발췌: {prose[:300]}\n"
        items += f"  표 포함 여부: {'있음 (' + str(len(tables)) + '개)' if tables else '없음'}\n"
        if hyde:
            items += f"  HyDE 질문 (참고): {', '.join(hyde[:2])}\n"

    return LEGAL_PREFIX_PROMPT.format(
        part_title=part_title or "(없음)",
        chapter_title=chapter_title or "(없음)",
        section_title=section_title or "(없음)",
        prev_excerpt=prev_excerpt or "(문서 시작)",
        next_excerpt=next_excerpt or "(문서 끝)",
        chunks_block=items,
    )
```

---

## 3. 핵심 처리 함수

### 3-1. Claude CLI 호출 (enrich_aliases.py와 동일)

```python
def call_claude_cli(prompt: str) -> str:
    """Claude Code CLI를 -p 파이프 모드로 호출하여 결과 텍스트 반환."""
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)  # 중첩 세션 방지

    proc = subprocess.run(
        [CLAUDE_BIN, "-p",
         "--model", MODEL,
         "--dangerously-skip-permissions",
         "--no-session-persistence"],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )

    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        raise RuntimeError(f"Claude CLI 실패 (exit={proc.returncode}): {stderr}")

    return proc.stdout.strip()
```

### 3-2. 체크포인트 관리

```python
def load_checkpoint(batch_key: str) -> dict | None:
    """저장된 체크포인트 로드. 없으면 None."""
    cp = CHECKPOINT_DIR / f"{batch_key}.json"
    if cp.exists():
        try:
            return json.loads(cp.read_text())
        except Exception:
            return None
    return None


def save_checkpoint(batch_key: str, data: list[dict]):
    """배치 결과를 체크포인트로 저장."""
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    (CHECKPOINT_DIR / f"{batch_key}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2)
    )
```

### 3-3. Prefix 배치 생성 (재시도 포함)

```python
def generate_prefix_batch(prompt: str, batch_key: str,
                           id_field: str = "id") -> dict[str, str]:
    """배치의 각 항목에 대한 prefix 반환. {id: contextual_prefix}"""
    cached = load_checkpoint(batch_key)
    if cached is not None:
        return {item[id_field]: item["contextual_prefix"] for item in cached}

    for attempt in range(3):
        try:
            raw = call_claude_cli(prompt)

            # 코드블록 감싸기 제거
            raw = re.sub(r'^```json\s*', '', raw, flags=re.MULTILINE)
            raw = re.sub(r'^```\s*$', '', raw, flags=re.MULTILINE)
            raw = raw.strip()

            arr_match = re.search(r'\[.*\]', raw, re.DOTALL)
            if arr_match:
                raw = arr_match.group()

            result = json.loads(raw)
            if not isinstance(result, list):
                raise ValueError("배열이 아님")

            valid = [r for r in result
                     if isinstance(r, dict)
                     and r.get(id_field)
                     and r.get("contextual_prefix")]

            # 길이 검증 (경고만, 실패 아님)
            for item in valid:
                plen = len(item["contextual_prefix"])
                if plen < 30:
                    print(f"  [경고] {item[id_field]}: prefix 너무 짧음 ({plen}자)")
                elif plen > 250:
                    print(f"  [경고] {item[id_field]}: prefix 너무 김 ({plen}자)")

            save_checkpoint(batch_key, valid)
            return {item[id_field]: item["contextual_prefix"] for item in valid}

        except (json.JSONDecodeError, ValueError) as e:
            print(f"  [경고] {batch_key} 파싱 실패 (시도 {attempt+1}/3): {e}")
            if attempt < 2:
                time.sleep(2)
        except subprocess.TimeoutExpired:
            print(f"  [타임아웃] {batch_key} — Claude CLI 120초 초과 (시도 {attempt+1}/3)")
            if attempt < 2:
                time.sleep(5)
        except RuntimeError as e:
            err_msg = str(e)
            print(f"  [오류] {batch_key}: {err_msg}")
            if "rate" in err_msg.lower() or "limit" in err_msg.lower():
                print(f"  [Rate Limit] {batch_key} — 30초 대기")
                time.sleep(30)
            elif attempt < 2:
                time.sleep(3)

    save_checkpoint(batch_key, [])
    return {}
```

### 3-4. Prefix 파일 머지

```python
def merge_to_prefix_file(new_prefixes: dict[str, str], target_file: Path):
    """새 prefix들을 기존 통합 prefix JSON에 머지."""
    target_file.parent.mkdir(parents=True, exist_ok=True)

    existing = {}
    if target_file.exists():
        try:
            existing = json.loads(target_file.read_text())
        except Exception:
            existing = {}

    existing.update(new_prefixes)
    target_file.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2)
    )
```

---

## 4. 배치 계획 및 실행 함수

### 4-1. 배치 계획 생성

```python
def build_batch_plan(collection: str = "all") -> list[dict]:
    """
    모든 배치를 순서대로 나열.
    반환: [{"type": "ontology"|"legal", "branch": str,
            "batch_start": int, "batch_key": str}, ...]
    """
    plan = []

    if collection in ("ontology", "all"):
        for branch_file in sorted(ENTRIES_DIR.glob("*.json")):
            branch = branch_file.stem
            with open(branch_file, encoding="utf-8") as f:
                entries = json.load(f)
            for batch_start in range(0, len(entries), BATCH_SIZE_ONTO):
                batch_num = batch_start // BATCH_SIZE_ONTO
                batch_key = f"onto_{branch}_{batch_num:04d}"
                plan.append({
                    "type": "ontology",
                    "branch": branch,
                    "branch_file": str(branch_file),
                    "batch_start": batch_start,
                    "batch_key": batch_key,
                })

    if collection in ("legal", "all"):
        if LEGAL_DOC.exists():
            with open(LEGAL_DOC, encoding="utf-8") as f:
                doc = json.load(f)
            chunks = doc.get("chunks", [])
            for batch_start in range(0, len(chunks), BATCH_SIZE_LEGAL):
                batch_num = batch_start // BATCH_SIZE_LEGAL
                batch_key = f"legal_{batch_num:04d}"
                plan.append({
                    "type": "legal",
                    "batch_start": batch_start,
                    "batch_key": batch_key,
                })

    return plan
```

### 4-2. 브랜치 요약 생성 (`--gen-summaries`)

```python
def gen_branch_summaries():
    """각 브랜치의 요약을 LLM으로 생성하여 _branch_summaries.json에 저장."""
    PREFIX_DIR_ONTO.mkdir(parents=True, exist_ok=True)

    summaries = {}
    if SUMMARIES_FILE.exists():
        summaries = json.loads(SUMMARIES_FILE.read_text())

    for branch_file in sorted(ENTRIES_DIR.glob("*.json")):
        branch = branch_file.stem
        if branch in summaries:
            print(f"  [건너뜀] {branch} — 이미 요약 존재")
            continue

        with open(branch_file, encoding="utf-8") as f:
            entries = json.load(f)

        branch_ko = BRANCH_KO.get(branch, branch)
        tree = build_hierarchy_tree(entries)

        prompt = SUMMARY_PROMPT_TEMPLATE.format(
            branch_korean=branch_ko,
            hierarchy_tree=tree,
        )

        print(f"  [{branch}] 요약 생성 중...")
        try:
            summary = call_claude_cli(prompt)
            summaries[branch] = summary.strip()
            print(f"  → {summary.strip()[:80]}...")
        except Exception as e:
            print(f"  [오류] {branch} 요약 생성 실패: {e}")
            continue

    SUMMARIES_FILE.write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2)
    )
    print(f"\n브랜치 요약 저장 완료: {SUMMARIES_FILE}")
    print(f"  총 {len(summaries)}개 브랜치")
```

### 4-3. 단일 배치 처리

```python
def process_one_batch(batch_info: dict, summaries: dict) -> int:
    """단일 배치를 처리하고 prefix 파일에 머지. 생성된 prefix 수 반환."""
    btype = batch_info["type"]
    batch_key = batch_info["batch_key"]

    if btype == "ontology":
        branch = batch_info["branch"]
        branch_file = Path(batch_info["branch_file"])

        with open(branch_file, encoding="utf-8") as f:
            all_entries = json.load(f)

        batch = all_entries[batch_info["batch_start"]:
                           batch_info["batch_start"] + BATCH_SIZE_ONTO]

        prompt = make_ontology_prompt(batch, branch, summaries, all_entries)
        prefixes = generate_prefix_batch(prompt, batch_key, id_field="id")

        if prefixes:
            target = PREFIX_DIR_ONTO / f"{branch}.json"
            merge_to_prefix_file(prefixes, target)

        return len(prefixes)

    elif btype == "legal":
        with open(LEGAL_DOC, encoding="utf-8") as f:
            doc = json.load(f)
        all_chunks = doc.get("chunks", [])

        start = batch_info["batch_start"]
        batch = all_chunks[start: start + BATCH_SIZE_LEGAL]
        indices = list(range(start, min(start + BATCH_SIZE_LEGAL, len(all_chunks))))

        prompt = make_legal_prompt(batch, all_chunks, indices)
        prefixes = generate_prefix_batch(prompt, batch_key, id_field="chunk_id")

        if prefixes:
            target = PREFIX_DIR_LEGAL / "2025_housing_tax_v2.json"
            merge_to_prefix_file(prefixes, target)

        return len(prefixes)

    return 0
```

### 4-4. `run_once()` / `run_all()` / `print_status()`

```python
def run_once(collection: str = "all") -> bool:
    """미처리 배치 1개를 찾아 처리. 처리했으면 True, 모두 완료면 False."""
    summaries = load_summaries()
    plan = build_batch_plan(collection)
    total = len(plan)
    done = 0

    for batch_info in plan:
        if load_checkpoint(batch_info["batch_key"]) is not None:
            done += 1
            continue

        # 미처리 배치 발견 → 처리
        btype = batch_info["type"]
        batch_key = batch_info["batch_key"]
        print(f"[{done+1}/{total}] {batch_key} 처리 중 ({btype})...")

        count = process_one_batch(batch_info, summaries)
        print(f"  → {count}개 prefix 생성")
        print(f"  진행률: {done+1}/{total} ({(done+1)*100//total}%)")
        return True

    print(f"[완료] 모든 배치 처리 완료 ({total}/{total})")
    return False


def run_all(collection: str = "all"):
    """전체 배치 연속 처리."""
    summaries = load_summaries()
    plan = build_batch_plan(collection)
    total = len(plan)
    grand_total = 0

    print(f"총 배치: {total}개")

    for i, batch_info in enumerate(plan):
        if load_checkpoint(batch_info["batch_key"]) is not None:
            continue

        batch_key = batch_info["batch_key"]
        print(f"[{i+1}/{total}] {batch_key} 처리 중...")
        count = process_one_batch(batch_info, summaries)
        grand_total += count
        print(f"  → {count}개 prefix 생성")

    print(f"\n=== 완료 ===")
    print(f"총 생성된 prefix: {grand_total}개")
    print_status()


def load_summaries() -> dict:
    """브랜치 요약 로드. 없으면 빈 dict."""
    if SUMMARIES_FILE.exists():
        return json.loads(SUMMARIES_FILE.read_text())
    return {}


def print_status(collection: str = "all"):
    """진행 상황 출력."""
    plan = build_batch_plan(collection)
    total = len(plan)
    done = sum(1 for b in plan if load_checkpoint(b["batch_key"]) is not None)

    onto_plan = [b for b in plan if b["type"] == "ontology"]
    onto_done = sum(1 for b in onto_plan if load_checkpoint(b["batch_key"]) is not None)

    legal_plan = [b for b in plan if b["type"] == "legal"]
    legal_done = sum(1 for b in legal_plan if load_checkpoint(b["batch_key"]) is not None)

    print(f"=== Contextual Prefix 생성 진행률 ===")
    print(f"  전체: {done}/{total} ({done*100//total if total else 0}%)")
    print(f"  온톨로지: {onto_done}/{len(onto_plan)}")
    print(f"  법률문서: {legal_done}/{len(legal_plan)}")

    # 브랜치별 prefix 수
    print(f"\n=== 생성된 Prefix 수 ===")
    if PREFIX_DIR_ONTO.exists():
        for pf in sorted(PREFIX_DIR_ONTO.glob("*.json")):
            if pf.stem.startswith("_"):
                continue
            data = json.loads(pf.read_text())
            print(f"  {pf.stem}: {len(data)}개")

    if PREFIX_DIR_LEGAL.exists():
        for pf in sorted(PREFIX_DIR_LEGAL.glob("*.json")):
            data = json.loads(pf.read_text())
            print(f"  legal/{pf.stem}: {len(data)}개")
```

### 4-5. main()

```python
def main():
    parser = argparse.ArgumentParser(
        description="Contextual Retrieval 맥락 접두어 배치 생성"
    )
    parser.add_argument("--once", action="store_true",
                        help="미처리 배치 1개만 처리 후 종료 (cron용)")
    parser.add_argument("--all", action="store_true",
                        help="전체 배치 연속 처리")
    parser.add_argument("--status", action="store_true",
                        help="현재 진행 상황만 출력")
    parser.add_argument("--collection", choices=["ontology", "legal", "all"],
                        default="all",
                        help="대상 컬렉션 (기본: all)")
    parser.add_argument("--gen-summaries", action="store_true",
                        help="브랜치 요약만 생성 (사전 작업)")
    args = parser.parse_args()

    if args.status:
        print_status(args.collection)
        return

    # Claude Code CLI 바이너리 확인
    if not Path(CLAUDE_BIN).exists():
        print(f"[치명적 오류] Claude Code CLI 바이너리 없음: {CLAUDE_BIN}")
        sys.exit(1)

    if args.gen_summaries:
        gen_branch_summaries()
        return

    # 브랜치 요약 존재 확인 (온톨로지 처리 시 필요)
    if args.collection in ("ontology", "all") and not SUMMARIES_FILE.exists():
        print("[경고] 브랜치 요약이 없습니다. --gen-summaries를 먼저 실행하세요.")
        print("  자동으로 브랜치 요약을 생성합니다...")
        gen_branch_summaries()

    if args.once:
        run_once(args.collection)
    elif args.all:
        run_all(args.collection)
    else:
        # 기본: --once와 동일 (cron 호환)
        run_once(args.collection)


if __name__ == "__main__":
    main()
```

---

## 5. 출력 파일 포맷

### 5-1. 체크포인트 (배치별)

`ontology_data/ctx_checkpoints/onto_tax_0000.json`:
```json
[
  {
    "id": "tax_acquisition",
    "contextual_prefix": "부동산을 매수하거나 상속·증여받을 때 발생하는 거래세로, 일반인들이 '집 살 때 세금', '아파트 사면 세금 얼마' 등으로 검색하는 개념이다. 세금 분야의 핵심 용어로 양도소득세·재산세와 함께 부동산 3대 세금을 구성한다."
  },
  {
    "id": "tax_additional_penalty",
    "contextual_prefix": "세금 신고·납부 기한을 넘기거나 과소신고했을 때 원래 세금에 추가로 부과되는 벌금 성격의 세금으로, '세금 연체하면 얼마나 더 내야 하나' 같은 질문과 관련된다."
  }
]
```

### 5-2. 통합 prefix 파일

`ontology_data/contextual_prefixes/tax.json`:
```json
{
  "tax_acquisition": "부동산을 매수하거나 상속·증여받을 때 ...",
  "tax_additional_penalty": "세금 신고·납부 기한을 넘기거나 ...",
  "tax_capital_gains": "부동산을 팔아서 이익이 생겼을 때 ..."
}
```

`ontology_data/contextual_prefixes/_branch_summaries.json`:
```json
{
  "tax": "세금(tax) 분야는 부동산의 취득·보유·양도 각 단계에서 ...",
  "auction": "경매(auction) 분야는 법원 강제경매와 공매를 통한 ...",
  "contract": "계약/거래(contract) 분야는 부동산 매매·임대·도급 ..."
}
```
