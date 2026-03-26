# `index_phase2.py` 수정 사항 — Contextual Prefix 로딩 및 적용

> 목적: prefix 생성 완료 후, 재임베딩 시 prefix를 임베딩 텍스트에 prepend하여 Qdrant에 색인
> 수정 대상: `codes/embedding/index_phase2.py`

---

## 1. 수정 개요

| 수정 위치 | 현재 | 변경 후 |
|-----------|------|---------|
| `index_domain_ontology()` | prefix 없이 text 생성 | prefix 파일 로드 → text 앞에 prepend |
| `_build_ontology_text()` | `term + aliases + description` | `prefix + term + aliases + description` |
| `index_legal_docs()` | prefix 없이 text 생성 | prefix 파일 로드 → prose/table_fact에 prepend |
| `_expand_legal_chunks()` | hierarchy + prose/table_fact | prefix + hierarchy + prose/table_fact |

---

## 2. 온톨로지 수정

### 2-1. `_build_ontology_text()` 함수 수정

```python
# 현재 코드 (추정):
def _build_ontology_text(entry: dict) -> str:
    term = entry["term"]
    aliases = entry.get("aliases", [])
    description = entry.get("description", "")
    parts = [term]
    if aliases:
        parts.append(" | ".join(aliases))
    if description:
        parts.append(description)
    return "\n".join(parts)


# 수정 후:
def _build_ontology_text(entry: dict, prefix: str = "") -> str:
    """온톨로지 엔트리의 임베딩용 텍스트 생성.

    Args:
        entry: 온톨로지 엔트리 dict
        prefix: contextual prefix (있으면 텍스트 앞에 붙임)
    """
    term = entry["term"]
    aliases = entry.get("aliases", [])
    description = entry.get("description", "")
    parts = []
    if prefix:
        parts.append(prefix)
    parts.append(term)
    if aliases:
        parts.append(" | ".join(aliases))
    if description:
        parts.append(description)
    return "\n".join(parts)
```

### 2-2. `index_domain_ontology()` prefix 로딩

```python
def index_domain_ontology():
    """domain_ontology 컬렉션 인덱싱."""

    # ── Contextual Prefix 로딩 (선택적) ──
    prefixes = {}
    prefix_dir = ENTRIES_DIR.parent / "contextual_prefixes"
    if prefix_dir.exists():
        for pf in prefix_dir.glob("*.json"):
            if pf.stem.startswith("_"):  # _branch_summaries.json 제외
                continue
            with open(pf, encoding="utf-8") as f:
                prefixes.update(json.load(f))
        if prefixes:
            print(f"[INFO] Contextual prefix 로드: {len(prefixes)}개")
    # ─────────────────────────────────────

    # 기존 로직 ...
    all_entries = []
    for branch_file in sorted(ENTRIES_DIR.glob("*.json")):
        # ...

    # 텍스트 생성 시 prefix 적용
    texts = []
    for entry in all_entries:
        prefix = prefixes.get(entry["id"], "")
        texts.append(_build_ontology_text(entry, prefix))

    # 이하 임베딩 + upsert 로직은 동일 ...
```

**임베딩 텍스트 예시 (prefix 적용 후):**

```
부동산을 매수하거나 상속·증여받을 때 발생하는 거래세로, 일반인들이 '집 살 때 세금', '아파트 사면 세금 얼마' 등으로 검색하는 개념이다. 세금 분야의 핵심 용어로 양도소득세·재산세와 함께 부동산 3대 세금을 구성한다.
취득세
다주택자 취득세 중과세율 | 집 여러 채 살 때 취득세 | 취등록세 | ...
부동산·차량 등 과세대상 물건을 취득한 자가 납부하는 지방세...
```

---

## 3. 법률문서 수정

### 3-1. `_expand_legal_chunks()` prefix 적용

```python
def _expand_legal_chunks(chunks: list[dict],
                          prefixes: dict[str, str] = None) -> list[dict]:
    """
    법률문서 base chunk → 확장 포인트 (prose, table_fact, hyde).

    Args:
        chunks: 원본 청크 리스트
        prefixes: {chunk_id: contextual_prefix} (없으면 prefix 미적용)
    """
    if prefixes is None:
        prefixes = {}

    points = []
    for chunk in chunks:
        chunk_id = chunk["chunk_id"]
        hier = chunk.get("hierarchy", {})
        hier_path = " > ".join(filter(None, [
            hier.get("part_title", ""),
            hier.get("chapter_title", ""),
            hier.get("section_title", ""),
        ]))

        prefix = prefixes.get(chunk_id, "")

        # ── Type 1: PROSE ──
        prose = chunk.get("content", {}).get("prose", "")
        if prose:
            text_parts = []
            if prefix:
                text_parts.append(prefix)
            if hier_path:
                text_parts.append(hier_path)
            text_parts.append(prose)
            text = "\n\n".join(text_parts)

            points.append({
                "chunk_id": chunk_id,
                "chunk_type": "prose",
                "text": text,
                # ... payload 필드들 ...
            })

        # ── Type 2: TABLE_FACT (행별) ──
        for table in chunk.get("content", {}).get("tables", []):
            for i, row_fact in enumerate(table.get("row_facts", [])):
                text_parts = []
                if prefix:
                    text_parts.append(prefix)
                if hier_path:
                    text_parts.append(hier_path)
                text_parts.append(row_fact)
                text = "\n\n".join(text_parts)

                points.append({
                    "chunk_id": chunk_id,
                    "chunk_type": "table_fact",
                    "text": text,
                    # ... payload 필드들 ...
                })

        # ── Type 3: HYDE (prefix 적용 안 함) ──
        hyde_questions = chunk.get("retrieval", {}).get("hyde_questions", [])
        if hyde_questions:
            text = "\n".join(hyde_questions)
            # prefix를 적용하지 않음: HyDE 질문은 사용자 질의를 시뮬레이션하는 것이므로
            # 맥락 prefix 없이 원본 그대로 임베딩해야 자연스러운 질의 매칭이 가능

            points.append({
                "chunk_id": chunk_id,
                "chunk_type": "hyde",
                "text": text,
                # ... payload 필드들 ...
            })

    return points
```

### 3-2. `index_legal_docs()` prefix 로딩

```python
def index_legal_docs():
    """legal_docs 컬렉션 인덱싱."""

    # ── Contextual Prefix 로딩 (선택적) ──
    legal_prefix_file = (PROJECT_ROOT / "data" / "domain_ontology" / "parsed"
                         / "contextual_prefixes" / "2025_housing_tax_v2.json")
    legal_prefixes = {}
    if legal_prefix_file.exists():
        with open(legal_prefix_file, encoding="utf-8") as f:
            legal_prefixes = json.load(f)
        if legal_prefixes:
            print(f"[INFO] Legal contextual prefix 로드: {len(legal_prefixes)}개")
    # ─────────────────────────────────────

    # 기존 로직: JSON 로드
    with open(LEGAL_DOC, encoding="utf-8") as f:
        doc = json.load(f)
    chunks = doc.get("chunks", [])

    # 확장 시 prefix 전달
    points = _expand_legal_chunks(chunks, prefixes=legal_prefixes)

    # 이하 임베딩 + upsert 로직은 동일 ...
```

---

## 4. HyDE 타입에 prefix를 적용하지 않는 이유

HyDE(Hypothetical Document Embeddings) 청크는 **사용자가 검색창에 입력할 법한 질문**을 시뮬레이션한 것이다:

```
"집 사고 나서 취득세 언제까지 신고해야 하나요?"
"상속받은 집 취득세 신고 기한이 얼마나 되나요?"
```

이 텍스트에 문서 맥락 prefix를 붙이면:

```
"《2025 주택과 세금》 제1편 취득세 신고납부 절차를 설명하는 부분으로...
집 사고 나서 취득세 언제까지 신고해야 하나요?"
```

이렇게 되면 사용자의 실제 질의("취득세 신고 기한")와의 코사인 유사도가 오히려 **하락**한다. HyDE의 목적은 "사용자 질의 ↔ HyDE 질문" 간의 벡터 거리를 최소화하는 것이므로, prefix를 붙이지 않는 것이 맞다.

**적용 요약:**
| chunk_type | prefix 적용 | 이유 |
|-----------|------------|------|
| prose | O | 문서 맥락이 추가되어 질의-문서 매칭 향상 |
| table_fact | O | 행 단독으로는 맥락 부족, prefix가 표/섹션 맥락 보완 |
| hyde | **X** | 사용자 질의 시뮬레이션, prefix 추가 시 매칭 정밀도 하락 |

---

## 5. 재인덱싱 실행

모든 prefix가 생성된 후 수동으로 실행:

```bash
# 1. prefix 생성 완료 확인
python3 scripts/contextual_prefix.py --status

# 출력 예시:
# === Contextual Prefix 생성 진행률 ===
#   전체: 170/170 (100%)
#   온톨로지: 143/143
#   법률문서: 27/27

# 2. (선택) A/B 테스트용 임시 컬렉션 인덱싱
python3 codes/embedding/index_phase2.py --collection domain_ontology_ctx_test

# 3. 본 컬렉션 재인덱싱
python3 codes/embedding/index_phase2.py --force

# 4. 검색 테스트 실행
python3 codes/embedding/search_test_phase2.py
```

---

## 6. Fallback 동작

prefix 파일이 없거나 특정 엔트리의 prefix가 빠져 있어도 정상 동작:

```python
prefix = prefixes.get(entry["id"], "")  # 없으면 빈 문자열
# prefix가 빈 문자열이면 기존과 동일하게 동작 (parts에 추가되지 않음)
if prefix:
    parts.append(prefix)
```

이로써 기존 인덱싱 파이프라인과 **100% 하위 호환** 유지.
