# `codes/ontology/prune_aliases.py` — 상세 코드 설계

> 목적: 온톨로지 엔트리의 과다 alias를 소급 정리하여 임베딩 벡터 희석 해소
> 패턴 원본: `codes/ontology/apply_slang_aliases.py`
> 선행 문서: `01_implementation_plan.md` §1

---

## 0. 핵심 개념 설명

### 0-1. 임베딩(Embedding)이란?

> **비유**: 사과, 바나나, 자동차라는 단어가 있다고 하자. 사람은 "사과와 바나나는 과일이니까 비슷하고, 자동차는 다르다"는 것을 안다. 컴퓨터도 이런 관계를 이해하려면 각 단어를 **숫자의 나열(벡터)**로 변환해야 한다. 예를 들어:
> - 사과 → [0.9, 0.1, 0.8] (과일 특성 높음)
> - 바나나 → [0.8, 0.2, 0.7] (사과와 비슷한 위치)
> - 자동차 → [0.1, 0.9, 0.1] (완전히 다른 위치)
>
> 이렇게 단어/문장을 고차원 벡터(우리는 1024차원)로 변환하는 것이 **임베딩**이다. 벡터 간 거리(코사인 유사도)가 가까울수록 의미가 비슷하다.

### 0-2. 벡터 희석(Vector Dilution) 문제

우리 시스템에서 온톨로지 엔트리는 다음과 같이 하나의 텍스트로 조합되어 임베딩된다:

```
[contextual_prefix]
취득세                          ← 핵심 용어
다주택자 취득세 중과세율 | 집 살 때 세금 | ...  ← aliases (" | "로 연결)
1세대 2주택 조정대상지역 취득 시 8% 중과...     ← description
```

이 전체 텍스트가 BGE-M3 모델을 통해 **1024차원 벡터 하나**로 압축된다.

**문제**: alias가 10개일 때와 25개일 때를 비교하면:

```
[10개 alias] "취득세 | 다주택자 취득세 | 집 살 때 세금 | ..."
→ 벡터가 "취득세" 의미에 집중 (핵심 개념 밀도 높음)

[25개 alias] "취득세 | 다주택자 취득세 | 집 살 때 세금 | 줍줍 뜻 | 줍줍이 뭐야 | ..."
→ 벡터가 여러 방향으로 분산 (핵심 개념 밀도 낮음)
```

> **비유**: 커피 한 잔에 설탕 2스푼을 넣으면 달콤하다. 하지만 같은 설탕 2스푼을 물 10리터에 넣으면 맛을 느끼기 어렵다. alias가 너무 많으면 핵심 의미가 벡터 공간에서 "희석"되는 것과 같다.

### 0-3. 코사인 유사도(Cosine Similarity)

두 벡터가 얼마나 같은 방향을 가리키는지 측정하는 값 (0~1):

```
cos(A, B) = (A · B) / (|A| × |B|)

1.0 = 완전히 같은 방향 (의미 동일)
0.0 = 직교 (관련 없음)
```

> **비유**: 나침반 두 개가 있다고 하자. 둘 다 북쪽을 가리키면 유사도 = 1.0이다. 하나는 북쪽, 하나는 동쪽이면 유사도 ≈ 0이다. 임베딩에서 "취득세"와 "집 살 때 세금"은 비슷한 방향(유사도 높음)이지만, "취득세"와 "줍줍이 뭐야"는 다른 방향(유사도 낮음)을 가리킨다.

### 0-4. 보호 Alias (Protected Aliases)

슬랭 매핑 중 `confidence: "manual_verified"`로 표시된 항목은 사람이 직접 검증한 매핑이다. 이들은 높은 품질이 보장되므로 pruning에서 제외해야 한다.

반면 `confidence: "rule_based"`는 자동 규칙으로 생성된 매핑으로, 부정확할 수 있어 pruning 후보가 된다.

---

## 1. 전체 구조

```python
#!/usr/bin/env python3
"""
prune_aliases.py — 온톨로지 엔트리 alias 소급 정리 스크립트.

Phase 2A에서 alias 확장(+359개) 후 Set A가 -2%p 회귀한 문제를 해결.
벡터 희석을 유발하는 저품질 alias를 제거하여 임베딩 품질을 회복한다.

사용법:
    python codes/ontology/prune_aliases.py                  # dry-run (기본)
    python codes/ontology/prune_aliases.py --apply           # 실제 적용
    python codes/ontology/prune_aliases.py --apply --no-embed  # GPU 없이 휴리스틱
    python codes/ontology/prune_aliases.py --max-aliases 18  # 엔트리당 최대 수

동작:
    1) slang_alias_mapping.json에서 보호 alias 세트 구축
    2) entries/*.json에서 max-aliases 초과 엔트리 식별
    3) 품질 점수 기반으로 최저 품질 alias부터 제거
    4) 결과 저장 + 통계 출력 + prune_log.json 기록
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# ─────────────── 경로 설정 ─────────────────────────────────────

_ws = Path("/workspace")
PROJECT_ROOT = _ws if _ws.exists() else Path("/home/gon/ws/rag")
ENTRIES_DIR = PROJECT_ROOT / "ontology_data" / "entries"
DEFAULT_MAPPING = PROJECT_ROOT / "ontology_data" / "slang_alias_mapping.json"

MAX_ALIASES_PER_ENTRY = 18   # Phase 2A 후속: 20 → 18
MIN_ALIASES = 2               # schema.py 최소 요구
SIMILARITY_THRESHOLD = 0.75   # 이하 alias는 저품질 후보

# 자동 생성 질문 패턴 (expand_slang_aliases.py가 생성)
QUERY_TEMPLATE_PATTERN = re.compile(
    r'.+\s+(뜻|이 뭐야|하면 어떻게 돼|이 뭐|뭐야)$'
)
```

---

## 2. 보호 Alias 세트 구축

`slang_alias_mapping.json`에서 `manual_verified` 항목만 추출하여 엔트리별 보호 세트를 만든다.

```python
def build_protected_aliases(mapping_path: Path) -> dict[str, set[str]]:
    """엔트리별 보호 alias 세트를 구축한다.

    보호 대상: confidence가 "manual_verified"인 슬랭의 본체 + 전체 variants.
    이 alias들은 사람이 검증한 정확한 매핑이므로 절대 삭제하지 않는다.

    Returns:
        {entry_id: {"영끌", "영끌 뜻", "영끌 대출", ...}}
    """
    if not mapping_path.exists():
        print(f"[경고] 매핑 파일 없음: {mapping_path} → 보호 세트 비어있음")
        return {}

    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    protected: dict[str, set[str]] = {}

    for slang, info in mapping.items():
        if info.get("confidence") != "manual_verified":
            continue

        # 슬랭 본체 + 모든 변형을 보호 대상에 추가
        all_aliases = [slang] + info.get("variants", [])

        for entry_id in info.get("target_entries", []):
            if entry_id not in protected:
                protected[entry_id] = set()
            protected[entry_id].update(
                a.strip() for a in all_aliases if a.strip()
            )

    total_protected = sum(len(v) for v in protected.values())
    print(f"[prune] 보호 alias: {total_protected}개 "
          f"({len(protected)}개 엔트리에 분포)")

    return protected
```

### 동작 원리

`slang_alias_mapping.json` 구조:
```json
{
  "영끌": {
    "formal_terms": ["최대한도 대출"],
    "variants": ["영끌 뜻", "영끌 대출", "영끌 매수"],
    "target_entries": ["loan_collateral", "loan_housing_urban_fund"],
    "confidence": "manual_verified"  ← 이것만 보호
  },
  "줍줍": {
    "confidence": "rule_based"       ← 이것은 보호 안 함
  }
}
```

`manual_verified`인 "영끌"의 경우:
- `loan_collateral` 엔트리에서 "영끌", "영끌 뜻", "영끌 대출", "영끌 매수"는 절대 삭제 불가
- 나머지 alias들은 품질 점수에 따라 삭제 후보가 됨

---

## 3. 슬랭 alias 역인덱스

어떤 alias가 슬랭 매핑에서 온 것인지 추적하기 위한 역인덱스를 구축한다.

```python
def build_slang_alias_index(mapping_path: Path) -> dict[str, dict[str, str]]:
    """alias → (origin, confidence) 역인덱스를 구축한다.

    Returns:
        {entry_id: {alias_str: confidence_level}}
        예: {"loan_collateral": {"영끌": "manual_verified", "영끌 뜻": "manual_verified"}}
    """
    if not mapping_path.exists():
        return {}

    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    index: dict[str, dict[str, str]] = {}

    for slang, info in mapping.items():
        confidence = info.get("confidence", "unknown")
        all_aliases = [slang] + info.get("variants", [])

        for entry_id in info.get("target_entries", []):
            if entry_id not in index:
                index[entry_id] = {}
            for alias in all_aliases:
                alias = alias.strip()
                if alias:
                    index[entry_id][alias] = confidence

    return index
```

---

## 4. 품질 점수 계산

### 4-1. 휴리스틱 모드 (`--no-embed`)

GPU가 없는 환경에서 사용. 임베딩 유사도 대신 규칙 기반으로 점수를 매긴다.

```python
def compute_heuristic_scores(
    entry: dict,
    slang_index: dict[str, str],
    protected: set[str],
) -> list[tuple[str, float, str]]:
    """각 alias에 휴리스틱 품질 점수를 부여한다.

    점수 기준:
        1.0 — 원본 alias (슬랭 매핑에 없는 기존 alias)
        0.9 — manual_verified 슬랭 (보호 대상, 실제로는 삭제 안 됨)
        0.5 — rule_based 슬랭 alias
        0.2 — 쿼리 템플릿 패턴 ("X 뜻", "X이 뭐야", "X 하면 어떻게 돼")

    Returns:
        [(alias, score, reason), ...] — score 오름차순 정렬
    """
    scored = []

    for alias in entry.get("aliases", []):
        # 보호 alias는 항상 최고 점수
        if alias in protected:
            scored.append((alias, 0.95, "protected"))
            continue

        # 쿼리 템플릿 패턴 체크 (최저 품질)
        if QUERY_TEMPLATE_PATTERN.match(alias):
            scored.append((alias, 0.2, "query_template"))
            continue

        # 슬랭 매핑 출처 확인
        confidence = slang_index.get(alias, None)

        if confidence is None:
            # 원본 alias (슬랭 확장 이전부터 있던 것)
            scored.append((alias, 1.0, "original"))
        elif confidence == "manual_verified":
            scored.append((alias, 0.9, "slang_verified"))
        elif confidence == "rule_based":
            scored.append((alias, 0.5, "slang_rule"))
        else:
            scored.append((alias, 0.5, "slang_unknown"))

    # 점수 오름차순 (낮은 점수 = 먼저 제거)
    scored.sort(key=lambda x: x[1])
    return scored
```

### 4-2. 임베딩 유사도 모드 (기본, GPU 필요)

BGE-M3로 `entry["term"]`과 각 alias의 코사인 유사도를 계산한다.

```python
def compute_embedding_scores(
    entries_over_limit: list[dict],
    slang_index_all: dict[str, dict[str, str]],
    protected_all: dict[str, set[str]],
) -> dict[str, list[tuple[str, float, str]]]:
    """BGE-M3 임베딩 유사도 기반으로 alias 품질 점수를 계산한다.

    과정:
        1) 초과 엔트리의 모든 term + alias를 수집
        2) BGE-M3로 일괄 임베딩 (배치 처리)
        3) 각 alias의 코사인 유사도 = cos(term_vector, alias_vector)
        4) 쿼리 템플릿 패턴은 유사도와 무관하게 0.2 부여

    Returns:
        {entry_id: [(alias, score, reason), ...]}
    """
    import numpy as np

    # embedder 초기화 (GPU 필요)
    sys.path.insert(0, str(PROJECT_ROOT / "codes" / "embedding"))
    from embedder_bgem3 import embed_query

    # Step 1: 임베딩할 텍스트 수집
    texts = []
    text_map = []  # (entry_id, "term"|"alias", alias_str)

    for entry in entries_over_limit:
        eid = entry["id"]
        term = entry["term"]

        texts.append(term)
        text_map.append((eid, "term", term))

        for alias in entry.get("aliases", []):
            texts.append(alias)
            text_map.append((eid, "alias", alias))

    print(f"[prune] 임베딩 대상: {len(texts)}개 텍스트")

    # Step 2: 배치 임베딩
    # embed_query()는 단일 쿼리용이므로, 배치 처리를 위해 직접 호출
    vectors = []
    for text in texts:
        dense, _, _ = embed_query(text)
        vectors.append(np.array(dense))

    vectors = np.array(vectors)

    # Step 3: 엔트리별 유사도 계산
    result: dict[str, list[tuple[str, float, str]]] = {}

    # term 벡터 인덱스 추출
    term_indices = {}
    for i, (eid, ttype, _) in enumerate(text_map):
        if ttype == "term":
            term_indices[eid] = i

    for i, (eid, ttype, alias_str) in enumerate(text_map):
        if ttype != "alias":
            continue

        if eid not in result:
            result[eid] = []

        protected = protected_all.get(eid, set())
        slang_idx = slang_index_all.get(eid, {})

        # 보호 alias
        if alias_str in protected:
            result[eid].append((alias_str, 0.95, "protected"))
            continue

        # 쿼리 템플릿
        if QUERY_TEMPLATE_PATTERN.match(alias_str):
            result[eid].append((alias_str, 0.2, "query_template"))
            continue

        # 코사인 유사도 계산
        term_idx = term_indices.get(eid)
        if term_idx is not None:
            term_vec = vectors[term_idx]
            alias_vec = vectors[i]
            cos_sim = float(
                np.dot(term_vec, alias_vec)
                / (np.linalg.norm(term_vec) * np.linalg.norm(alias_vec) + 1e-9)
            )
        else:
            cos_sim = 0.5  # fallback

        # confidence 정보 결합
        confidence = slang_idx.get(alias_str, None)
        if confidence is None:
            reason = f"original(sim={cos_sim:.3f})"
        else:
            reason = f"slang_{confidence}(sim={cos_sim:.3f})"

        result[eid].append((alias_str, cos_sim, reason))

    # 각 엔트리별로 점수 오름차순 정렬
    for eid in result:
        result[eid].sort(key=lambda x: x[1])

    return result
```

> **배치 임베딩 설명**: `embed_query()`를 텍스트마다 한 번씩 호출하면 느리지만, 46개 초과 엔트리의 term + alias를 합쳐도 최대 1000개 미만이므로 수 분 내에 완료된다. 프로덕션에서는 `model.encode(texts, batch_size=64)`로 일괄 처리하면 10배 이상 빨라진다.

---

## 5. Pruning 결정 엔진

```python
@dataclass
class PruneDecision:
    """하나의 엔트리에 대한 pruning 결정."""
    entry_id: str
    term: str
    before_count: int
    after_count: int
    kept: list[str]
    pruned: list[tuple[str, float, str]]  # (alias, score, reason)
    warning: str = ""


def decide_pruning(
    entry: dict,
    max_aliases: int,
    protected: set[str],
    scored_aliases: list[tuple[str, float, str]],
) -> PruneDecision:
    """엔트리의 alias를 품질 점수 기반으로 정리한다.

    알고리즘:
        1) 현재 alias 수가 max_aliases 이하이면 → 변경 없음
        2) 제거 필요 수 = 현재 수 - max_aliases
        3) 점수 최저인 비보호 alias부터 제거
        4) 보호 alias는 절대 제거하지 않음
        5) 최소 MIN_ALIASES(2)개는 유지

    Returns:
        PruneDecision 객체 (kept/pruned 목록 포함)
    """
    current_aliases = entry.get("aliases", [])
    if len(current_aliases) <= max_aliases:
        return PruneDecision(
            entry_id=entry["id"],
            term=entry["term"],
            before_count=len(current_aliases),
            after_count=len(current_aliases),
            kept=current_aliases,
            pruned=[],
        )

    to_remove_count = len(current_aliases) - max_aliases

    # 점수 lookup
    score_map = {alias: (score, reason) for alias, score, reason in scored_aliases}

    # 제거 후보: 보호 아닌 것, 점수 오름차순
    candidates = []
    for alias, score, reason in scored_aliases:
        if alias in protected:
            continue
        candidates.append((alias, score, reason))

    # 낮은 점수부터 제거
    pruned = []
    pruned_set = set()
    for alias, score, reason in candidates:
        if len(pruned) >= to_remove_count:
            break
        pruned.append((alias, score, reason))
        pruned_set.add(alias)

    # 유지할 alias 목록 (원래 순서 보존)
    kept = [a for a in current_aliases if a not in pruned_set]

    # 최소 alias 수 보장
    if len(kept) < MIN_ALIASES:
        # pruned에서 점수 높은 것부터 복원
        while len(kept) < MIN_ALIASES and pruned:
            restored = pruned.pop()
            kept.append(restored[0])
            pruned_set.discard(restored[0])

    # 경고: 보호 alias 때문에 목표 미달성
    warning = ""
    if len(kept) > max_aliases:
        over = len(kept) - max_aliases
        warning = (f"보호 alias {len(protected)}개로 인해 "
                   f"max_aliases({max_aliases}) 초과 {over}개 유지")

    return PruneDecision(
        entry_id=entry["id"],
        term=entry["term"],
        before_count=len(current_aliases),
        after_count=len(kept),
        kept=kept,
        pruned=pruned,
        warning=warning,
    )
```

### Pruning 알고리즘 시각화

```
엔트리 "청약" (현재 25개 alias, max=18)

  점수순 정렬:
    0.20  "줍줍이 뭐야"         ← query_template → 제거 ①
    0.20  "줍줍 하면 어떻게 돼"  ← query_template → 제거 ②
    0.20  "로또청약 뜻"         ← query_template → 제거 ③
    0.50  "로또청약"            ← slang_rule     → 제거 ④
    0.50  "분상제"              ← slang_rule     → 제거 ⑤
    0.50  "특공"                ← slang_rule     → 제거 ⑥
    0.50  "사전청약"            ← slang_rule     → 제거 ⑦
    0.95  "줍줍"                ← protected      → 유지
    0.95  "줍줍 뜻"             ← protected      → 유지
    1.00  "청약통장"            ← original       → 유지
    1.00  "주택청약"            ← original       → 유지
    ...나머지 14개 original...   → 유지

  결과: 25개 → 18개 (7개 제거)
```

---

## 6. 통계 리포터

```python
@dataclass
class PruneStats:
    """전체 pruning 통계."""
    total_entries: int = 0
    entries_over_limit: int = 0
    total_aliases_before: int = 0
    total_aliases_after: int = 0
    aliases_pruned: int = 0
    pruned_by_reason: dict = field(default_factory=dict)  # reason → count
    entries_still_over: int = 0  # 보호 alias로 목표 미달성
    decisions: list = field(default_factory=list)

    def add_decision(self, d: PruneDecision):
        self.decisions.append(d)
        self.aliases_pruned += len(d.pruned)
        for _, _, reason in d.pruned:
            # reason에서 카테고리 추출: "query_template", "slang_rule(sim=0.3)" → "slang_rule"
            category = reason.split("(")[0]
            self.pruned_by_reason[category] = self.pruned_by_reason.get(category, 0) + 1
        if d.warning:
            self.entries_still_over += 1

    def print_report(self):
        print(f"\n{'='*60}")
        print(f"  Alias Pruning 결과")
        print(f"{'='*60}")
        print(f"  전체 엔트리:     {self.total_entries}")
        print(f"  초과 엔트리:     {self.entries_over_limit}")
        print(f"  Alias (전):      {self.total_aliases_before}")
        print(f"  Alias (후):      {self.total_aliases_after}")
        print(f"  제거됨:          {self.aliases_pruned}")
        print(f"  목표 미달성:     {self.entries_still_over}개 (보호 alias 초과)")
        print()
        print(f"  제거 사유별:")
        for reason, count in sorted(self.pruned_by_reason.items(),
                                     key=lambda x: -x[1]):
            print(f"    {reason:20s}: {count}개")
        print()
        for d in self.decisions:
            status = f"{'⚠' if d.warning else '✓'}"
            print(f"  {status} {d.entry_id}: {d.before_count} → {d.after_count} "
                  f"(-{len(d.pruned)})")
            if d.warning:
                print(f"    {d.warning}")
            for alias, score, reason in d.pruned[:5]:
                print(f"    [-] {score:.2f} {reason:20s} | {alias}")
            if len(d.pruned) > 5:
                print(f"    ... 외 {len(d.pruned)-5}개")
```

---

## 7. 메인 오케스트레이션

```python
def main():
    parser = argparse.ArgumentParser(
        description="온톨로지 alias 소급 정리 (Phase 2A 후속)"
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="실제 적용 (기본: dry-run)",
    )
    parser.add_argument(
        "--max-aliases", type=int, default=MAX_ALIASES_PER_ENTRY,
        help=f"엔트리당 최대 alias 수 (기본: {MAX_ALIASES_PER_ENTRY})",
    )
    parser.add_argument(
        "--no-embed", action="store_true",
        help="GPU 없이 휴리스틱 모드 (임베딩 유사도 계산 스킵)",
    )
    parser.add_argument(
        "--mapping", type=str, default=str(DEFAULT_MAPPING),
        help="슬랭 매핑 JSON 경로",
    )
    parser.add_argument(
        "--entries-dir", type=str, default=str(ENTRIES_DIR),
        help="온톨로지 엔트리 디렉토리",
    )
    args = parser.parse_args()

    mapping_path = Path(args.mapping)
    entries_dir = Path(args.entries_dir)
    max_aliases = args.max_aliases

    mode = "APPLY" if args.apply else "DRY-RUN"
    scoring = "HEURISTIC" if args.no_embed else "EMBEDDING"
    print(f"[prune] 모드: {mode} | 점수 방식: {scoring}")
    print(f"[prune] 최대 aliases/entry: {max_aliases}")

    # ──── Step 1: 보호 alias + 슬랭 역인덱스 구축 ────
    protected_all = build_protected_aliases(mapping_path)
    slang_index_all = build_slang_alias_index(mapping_path)

    # ──── Step 2: 전체 엔트리 로딩 + 초과 식별 ────
    stats = PruneStats()
    all_entries_by_file: dict[Path, list[dict]] = {}

    for json_file in sorted(entries_dir.glob("*.json")):
        entries = json.loads(json_file.read_text(encoding="utf-8"))
        all_entries_by_file[json_file] = entries
        stats.total_entries += len(entries)
        for entry in entries:
            alias_count = len(entry.get("aliases", []))
            stats.total_aliases_before += alias_count

    # 초과 엔트리 수집
    entries_over = []
    for json_file, entries in all_entries_by_file.items():
        for entry in entries:
            if len(entry.get("aliases", [])) > max_aliases:
                entries_over.append(entry)
                stats.entries_over_limit += 1

    print(f"[prune] 전체 {stats.total_entries}개 엔트리, "
          f"초과 {stats.entries_over_limit}개")

    if not entries_over:
        print("[prune] 초과 엔트리 없음 — 작업 종료")
        return

    # ──── Step 3: 품질 점수 계산 ────
    if args.no_embed:
        # 휴리스틱 모드
        scores_by_entry = {}
        for entry in entries_over:
            eid = entry["id"]
            protected = protected_all.get(eid, set())
            slang_idx = slang_index_all.get(eid, {})
            scores_by_entry[eid] = compute_heuristic_scores(
                entry, slang_idx, protected
            )
    else:
        # 임베딩 유사도 모드
        scores_by_entry = compute_embedding_scores(
            entries_over, slang_index_all, protected_all
        )

    # ──── Step 4: Pruning 결정 ────
    decisions_map: dict[str, PruneDecision] = {}
    for entry in entries_over:
        eid = entry["id"]
        protected = protected_all.get(eid, set())
        scored = scores_by_entry.get(eid, [])
        decision = decide_pruning(entry, max_aliases, protected, scored)
        decisions_map[eid] = decision
        stats.add_decision(decision)

    # ──── Step 5: 결과 적용 또는 미리보기 ────
    if args.apply:
        # 백업 생성
        backup_dir = entries_dir / f"_backup_{datetime.now():%Y%m%d_%H%M%S}"
        backup_dir.mkdir(exist_ok=True)
        for json_file in all_entries_by_file:
            shutil.copy2(json_file, backup_dir / json_file.name)
        print(f"[prune] 백업 생성: {backup_dir}")

        # JSON 파일에 반영
        for json_file, entries in all_entries_by_file.items():
            modified = False
            for entry in entries:
                eid = entry["id"]
                if eid in decisions_map and decisions_map[eid].pruned:
                    entry["aliases"] = decisions_map[eid].kept
                    modified = True
            if modified:
                json_file.write_text(
                    json.dumps(entries, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                print(f"  Updated: {json_file.name}")

        # prune_log.json 기록 (롤백용)
        log_path = entries_dir / "prune_log.json"
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "max_aliases": max_aliases,
            "scoring_mode": scoring,
            "backup_dir": str(backup_dir),
            "decisions": [
                {
                    "entry_id": d.entry_id,
                    "term": d.term,
                    "before": d.before_count,
                    "after": d.after_count,
                    "pruned": [(a, s, r) for a, s, r in d.pruned],
                }
                for d in stats.decisions if d.pruned
            ],
        }
        log_path.write_text(
            json.dumps(log_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[prune] 로그 저장: {log_path}")

    # ──── Step 6: 통계 출력 ────
    stats.total_aliases_after = stats.total_aliases_before - stats.aliases_pruned
    stats.print_report()

    if args.apply and stats.aliases_pruned > 0:
        print(f"\n[prune] 다음 단계: 재색인 실행")
        print(f"  docker exec -it rag-embedding python "
              f"codes/embedding/index_phase2_v2.py --only ontology --force")


if __name__ == "__main__":
    main()
```

---

## 8. 기존 파일 수정

### 8-1. `apply_slang_aliases.py` line 28

```python
# 변경 전:
MAX_ALIASES_PER_ENTRY = 20  # Text Enrichment (2024) 경고: alias 과다 시 정규 질의 성능 하락

# 변경 후:
MAX_ALIASES_PER_ENTRY = 18  # Phase 2A 후속: 벡터 희석 해소 (20→18, 06_phase2a_results.md §9-5)
```

### 8-2. `validator.py` line 93 이후 추가

```python
            # aliases 최소 개수
            aliases = entry.get("aliases", [])
            if len(aliases) < MIN_ALIASES:
                print(f"  [경고] {branch}/{eid} aliases {len(aliases)}개 (최소 {MIN_ALIASES})")
                warnings += 1

            # ↓↓↓ 추가: aliases 최대 개수 ↓↓↓
            MAX_ALIASES = 18
            if len(aliases) > MAX_ALIASES:
                print(f"  [경고] {branch}/{eid} aliases {len(aliases)}개 (최대 {MAX_ALIASES})")
                warnings += 1
```

---

## 9. 실행 절차

```bash
# ──── Phase 1: Dry-run으로 영향 확인 ────
python codes/ontology/prune_aliases.py
# → 초과 엔트리 수, 제거 대상 alias 목록 출력 (파일 수정 없음)

# ──── Phase 2: 적용 (휴리스틱, GPU 없이 가능) ────
python codes/ontology/prune_aliases.py --apply --no-embed
# → entries/*.json 수정 + 백업 생성 + prune_log.json 기록

# ──── Phase 3: Validator 확인 ────
python codes/ontology/validator.py
# → 오류 0건, 경고에 max alias 관련 항목 없어야 함

# ──── Phase 4: 재색인 (Docker 컨테이너 내부) ────
docker exec -it rag-embedding \
    python codes/embedding/index_phase2_v2.py --only ontology --force
# → domain_ontology_v2 컬렉션 재구축

# ──── Phase 5: 벤치마크 (Docker 컨테이너 내부) ────
# Set A 단독 (목표 ≥79%)
docker exec -it rag-embedding \
    python codes/query/test_query_decomposition.py --set A

# 전체 회귀 체크
docker exec -it rag-embedding \
    python codes/query/test_query_decomposition.py
```

---

## 10. 예상 결과

### Pruning 대상 분석 (현재 데이터 기준)

| 초과 범위 | 엔트리 수 | 예상 제거 alias |
|-----------|----------|----------------|
| 25개 (max) | 1 | 7개 |
| 21-23개 | 3 | 3-5개씩 |
| 20개 | ~20 | 2개씩 |
| 19개 | ~22 | 1개씩 |
| **합계** | ~46 | **~100개** |

### 벤치마크 예상

| 세트 | 현재 | Pruning 후 예상 | 근거 |
|------|------|----------------|------|
| A | 77% | **79-80%** | 벡터 희석 해소 (-1.3%p → 0%p) |
| B | 60% | 59-60% | 보호 alias 보존, 미세 하락 가능 |
| C | 82% | 82% | 교차 도메인은 alias 수 영향 적음 |
| D | 58% | 58% | 구어체 alias 대부분 보존 |
| E | 54% | 54% | alias pruning 단독으로는 미미 |

---

## 11. 참고 문헌

| 출처 | 핵심 발견 | 본 작업 적용 |
|------|-----------|------------|
| Text Enrichment (2024) | alias 추가 시 -3.45%p 회귀 가능 | max 18 제한 근거 |
| Separating Semantic Expansion from Geometry (2025) | 의미적 품질이 임베딩 모델보다 중요 | 유사도 기반 pruning |
| Phase 2A 1차 테스트 (06_phase2a_results.md §3-3) | Baseline 79.3% → 78% (alias만으로 -1.3%p) | 제거 우선순위 설계 |
