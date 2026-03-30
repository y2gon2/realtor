# 온톨로지 슬랭 Alias 확장

> 작성일: 2026-03-28
> 선행 문서: `01_phase2a_quickwins_plan.md`
> 관련 코드: `codes/ontology/expand_slang_aliases.py`, `codes/ontology/apply_slang_aliases.py`
> 관련 데이터: `ontology_data/entries/*.json`, `ontology_data/slang_alias_mapping.json`
> 목적: 인터넷 슬랭 alias 200-500개를 온톨로지에 추가하여 Set E P@3 55% → 60% 개선

---

## 1. 문제 분석

### 1-1. 왜 슬랭이 검색에 실패하는가?

> **비유**: 전화번호부에 "홍길동"만 등록되어 있고 "길동이"라는 별명은 등록되지 않았으면, "길동이 전화번호"로 검색해도 찾을 수 없는 것과 같다.

현재 온톨로지 임베딩 과정:

```
엔트리 JSON:
  term: "갭투자"
  aliases: ["전세 레버리지 매입", "전세낀 매매", ...]
  description: "전세금을 끼고 적은 자기자본으로..."

       ↓ _build_ontology_text() 함수

임베딩 텍스트:
  "갭투자
   전세 레버리지 매입 | 전세낀 매매 | ...
   전세금을 끼고 적은 자기자본으로..."

       ↓ BGE-M3 임베딩

1024차원 Dense 벡터 하나
```

사용자가 "갭투"로 검색하면:
- "갭투" → 1024차원 질의 벡터
- 코사인 유사도 계산: "갭투" vs "갭투자 | 전세 레버리지 매입 | ..."
- **"갭투"가 aliases에 없으므로** 유사도가 낮음 → 검색 실패

### 1-2. Set E 실패 패턴 분석

Set E(혼합형, 100개)의 P@3 55% — 실패한 45개 질의 분석:

| 실패 유형 | 비율 | 예시 |
|----------|------|------|
| **슬랭 어휘 격차** | ~50% | "영끌", "줍줍", "갭투", "마피" |
| 다중 도메인 복합성 | ~25% | "재건축+양도세+규제" 3도메인 |
| 시사/트렌드 용어 | ~15% | "스트레스 DSR 3단계" |
| 질의 모호성 | ~10% | "대충 써도 되나요?" |

→ **슬랭 어휘 격차가 최대 원인** (22-23개 질의)

### 1-3. 한국 부동산 인터넷 슬랭의 유형

> **비유**: 은어(슬랭)가 만들어지는 방식은 마치 줄임말/별명이 생기는 과정과 같다. "스타벅스"가 "스벅"이 되고, "아이스 아메리카노"가 "아아"가 되는 것처럼.

| 유형 | 형성 방식 | 부동산 예시 | 정식 용어 |
|------|---------|-----------|---------|
| **음절 절단** | 긴 단어의 앞 글자만 취함 | 영끌, 갭투, 복비 | 영혼까지 끌어모아, 갭투자, 중개보수 |
| **합성어** | 두 단어를 합침 | 깡통전세, 부린이, 로또청약 | 역전세 위험, 부동산 초보, 고가 단지 청약 |
| **약어** | 영어+한국어 혼합 | 분상제, 투과지, 특공 | 분양가상한제, 투기과열지구, 특별공급 |
| **비유적 표현** | 감정/상황 비유 | 세금 폭탄, 똘똘한 한 채 | 다주택 중과세, 우량 1주택 전략 |
| **커뮤니티 은어** | 온라인 커뮤니티에서 발생 | 줍줍, 마피, 피 | 무순위 청약, 마이너스 프리미엄, 프리미엄 |

---

## 2. 스크립트 설계

### 2-1. 전체 데이터 플로우

```
Step 3-A: 슬랭 매핑 생성
┌─────────────────────────────────────────────┐
│ expand_slang_aliases.py                      │
│                                              │
│ SLANG_SEEDS (50개)                           │
│     + 엔트리 인덱스 (2,146개)                 │
│     ↓                                        │
│ 규칙 기반 매핑 (term/alias 부분 매칭)          │
│     ↓                                        │
│ slang_alias_mapping.json                     │
└─────────────────────────────────────────────┘
         ↓
Step 3-B: 엔트리 적용
┌─────────────────────────────────────────────┐
│ apply_slang_aliases.py                       │
│                                              │
│ slang_alias_mapping.json                     │
│     + entries/*.json (10개 branch 파일)        │
│     ↓                                        │
│ alias 배열에 슬랭+변형 추가 (중복 방지)        │
│     ↓                                        │
│ entries/*.json (수정됨)                        │
└─────────────────────────────────────────────┘
         ↓
Step 3-C: 재색인
┌─────────────────────────────────────────────┐
│ index_phase2_v2.py --only ontology --force   │
│                                              │
│ 수정된 entries/*.json → 재임베딩 → Qdrant     │
│ (약 2분 소요, 2,146 포인트)                   │
└─────────────────────────────────────────────┘
```

### 2-2. expand_slang_aliases.py — 슬랭 매핑 생성

**위치**: `codes/ontology/expand_slang_aliases.py`

**핵심 설계**:

```python
# ── 슬랭 시드 목록 (50개, 10개 도메인 커버) ──
SLANG_SEEDS = {
    "영끌":      {"hint": "최대한도 대출, 레버리지 투자",   "branch": "loan"},
    "깡통전세":  {"hint": "역전세, 보증금 미반환 위험",      "branch": "rental"},
    "줍줍":      {"hint": "무순위 청약, 잔여세대 청약",      "branch": "subscription"},
    "부린이":    {"hint": "부동산 초보 투자자",              "branch": "general"},
    "갭투":      {"hint": "갭투자, 전세 레버리지 매입",      "branch": "loan"},
    "복비":      {"hint": "중개보수, 중개수수료",            "branch": "contract"},
    "마피":      {"hint": "마이너스프리미엄",                "branch": "contract"},
    # ... 총 50개
}
```

**엔트리 매칭 알고리즘**:

> **비유**: "영끌"이라는 슬랭을 전화번호부에서 찾으려면, "영끌"이라는 이름은 없으니 힌트인 "최대한도 대출"로 검색하는 것. "대출"이 들어가는 엔트리를 찾으면 그것이 매핑 대상.

```python
def find_target_entries(formal_terms, branch_hint, entry_index):
    """힌트 용어를 기반으로 가장 적합한 온톨로지 엔트리 ID 찾기.

    매칭 방식:
    1. 정확 매칭: hint 용어가 기존 term/alias에 정확히 있는지
    2. 부분 매칭: hint 용어가 기존 term/alias에 부분적으로 포함되는지
    3. 도메인 필터: branch_hint로 도메인 범위 제한
    """
    candidates = set()
    for term in formal_terms:
        key = term.lower()
        # 정확 매칭
        if key in entry_index:
            candidates.add(entry_index[key]["id"])
        # 부분 매칭 (도메인 필터 적용)
        for idx_key, idx_val in entry_index.items():
            if key in idx_key or idx_key in key:
                if idx_val["branch"] == branch_hint:
                    candidates.add(idx_val["id"])
                    if len(candidates) >= 3:
                        break
    return list(candidates)[:3]
```

**규칙 기반 변형 생성**:

```python
# 각 슬랭에 대해 기본 변형 자동 생성
variants = [
    f"{slang} 뜻",           # "영끌 뜻"
    f"{slang}이 뭐야",        # "영끌이 뭐야"
    f"{slang} 하면 어떻게 돼", # "영끌 하면 어떻게 돼"
]
for term in formal_terms[:2]:
    variants.append(f"{slang} {term}")  # "영끌 대출", "영끌 레버리지"
```

### 2-3. 실행 방법

```bash
# 1. dry-run: 매핑 결과 미리보기 (파일 생성하지 않음... 은 아니고 JSON은 생성)
python3 codes/ontology/expand_slang_aliases.py --dry-run

# 2. 매핑 생성
python3 codes/ontology/expand_slang_aliases.py \
    --output ontology_data/slang_alias_mapping.json

# 출력 예시:
# [expand_slang] 슬랭 시드: 50개
# [expand_slang] 결과:
#   총 슬랭: 50
#   매칭 성공: 42
#   매칭 실패: 8
#   총 타겟 엔트리: 67
#   총 변형: 210
```

### 2-4. apply_slang_aliases.py — 엔트리 적용

**위치**: `codes/ontology/apply_slang_aliases.py`

**핵심 로직**:

```python
def apply_slang_to_entries(mapping_path, entries_dir, max_aliases=20, dry_run=False):
    """슬랭 매핑을 기존 온톨로지 엔트리의 aliases 배열에 추가.

    안전장치:
    1. 중복 방지: 이미 있는 alias는 스킵
    2. 한도 제한: 엔트리당 최대 max_aliases개 (기본 20개)
    3. dry-run: 실제 파일 변경 없이 미리보기
    """
    mapping = json.load(open(mapping_path))

    # 역인덱스: entry_id → [(slang, variants)]
    entry_to_slangs = {}
    for slang, info in mapping.items():
        for entry_id in info["target_entries"]:
            entry_to_slangs.setdefault(entry_id, []).append(
                (slang, info["variants"])
            )

    # 각 branch JSON 파일 처리
    for json_file in entries_dir.glob("*.json"):
        entries = json.load(open(json_file))
        for entry in entries:
            if entry["id"] not in entry_to_slangs:
                continue
            existing = set(entry["aliases"])
            for slang, variants in entry_to_slangs[entry["id"]]:
                for alias in [slang] + variants:
                    if alias not in existing and len(existing) < max_aliases:
                        entry["aliases"].append(alias)
                        existing.add(alias)
```

**`max_aliases = 20` 제한의 이유**:

Text Enrichment 논문 (2024)에서 경고: alias를 chunk text에 과도하게 삽입하면 정규 질의 성능이 하락할 수 있음 (Banking77 데이터셋에서 -3.45%p).

현재 평균 alias 수: 12개/엔트리. 20개 한도 내에서 8개의 여유가 있으므로, 슬랭 + 변형 5-8개를 추가하더라도 한도를 초과하지 않는다.

### 2-5. 실행 방법

```bash
# 1. dry-run: 변경 미리보기
python3 codes/ontology/apply_slang_aliases.py --dry-run

# 출력 예시:
# [DRY-RUN] loan_leverage: +6 aliases (→ 18개)
# [DRY-RUN] rental_risk: +5 aliases (→ 17개)
# ...
# 수정된 엔트리: 42
# 추가된 alias: 210
# 중복 스킵: 15
# 한도 초과 스킵: 3

# 2. 실제 적용
python3 codes/ontology/apply_slang_aliases.py

# 3. 재색인 (Docker 컨테이너 내)
python3 codes/embedding/index_phase2_v2.py --only ontology --force

# 출력 예시:
# [index] domain_ontology_v2: 2,146 포인트 재색인 완료 (123초)
```

---

## 3. 슬랭 시드 목록 상세 (50개)

### 3-1. 도메인별 분류

**대출/투자 (5개)**:

| 슬랭 | 정식 용어 | 설명 |
|------|---------|------|
| 영끌 | 최대한도 대출 | 영혼까지 끌어모아 대출받는 것 |
| 갭투 | 갭투자 | 전세를 끼고 적은 자본으로 매입 |
| 전세끼고 | 갭투자 | 갭투의 풀어쓴 표현 |
| 풀론 | 최대 대출 | LTV 한도까지 대출 |
| 마통 | 마이너스통장 | 마이너스 대출 통장 |

**임대차/전세 (4개)**:

| 슬랭 | 정식 용어 | 설명 |
|------|---------|------|
| 깡통전세 | 역전세 위험 | 전세가 > 매매가로 보증금 반환 불가 |
| 빌라왕 | 다주택 전세사기 | 다수 빌라를 전세로 운영하다 사기 |
| 전세 돌려막기 | 전세보증금 사기 | 새 세입자 보증금으로 이전 세입자 반환 |
| 역전세 | 전세가격 하락 | 전세 시세가 계약 시보다 하락 |

**청약/분양 (5개)**, **계약/거래 (7개)**, **세금 (4개)**, **경매 (5개)**, **재건축 (5개)**, **규제 (4개)**, **토지 (2개)**, **등기 (2개)**, **일반 (4개)** — 총 50개

### 3-2. 출력 매핑 예시 (slang_alias_mapping.json)

```json
{
  "영끌": {
    "formal_terms": ["최대한도 대출", "레버리지 투자"],
    "variants": ["영끌 뜻", "영끌이 뭐야", "영끌 하면 어떻게 돼",
                  "영끌 최대한도 대출", "영끌 레버리지 투자"],
    "target_entries": ["loan_leverage", "loan_limit"],
    "branch": "loan",
    "confidence": "rule_based"
  },
  "깡통전세": {
    "formal_terms": ["역전세 위험", "보증금 미반환"],
    "variants": ["깡통전세 뜻", "깡통전세이 뭐야",
                  "깡통전세 하면 어떻게 돼",
                  "깡통전세 역전세 위험", "깡통전세 보증금 미반환"],
    "target_entries": ["rental_reverse_lease", "rental_deposit_risk"],
    "branch": "rental",
    "confidence": "rule_based"
  }
}
```

---

## 4. 검증 및 품질 관리

### 4-1. 매핑 품질 검수

자동 매핑 후 수동 검수가 필수:

| 검수 항목 | 기준 | 조치 |
|----------|------|------|
| 매칭 정확도 | ≥ 90% (45/50) | 틀린 매핑 수동 수정 |
| 중복 매핑 | 동일 슬랭이 다른 엔트리에 | 가장 적합한 엔트리 1-2개만 유지 |
| 변형 자연스러움 | 실제 사용 여부 | 부자연스러운 변형 제거 |
| 타겟 부재 | 온톨로지에 대응 엔트리 없음 | 새 엔트리 생성 검토 |

### 4-2. Set A 회귀 모니터링

> **경고**: Text Enrichment 논문 (2024)에서 alias 추가가 정규 질의 성능을 하락시킬 수 있음을 확인. 반드시 Set A P@3가 79% 이상 유지되는지 확인.

```bash
# 재색인 후 Set A만 빠르게 검증
python3 test_query_decomposition.py --set A --setting full_rerank
# 기대: P@3 ≥ 79%
```

### 4-3. 성공 기준

| 지표 | 현재 | 목표 |
|------|------|------|
| Set E P@3 | 55% | ≥58% (+3%p) |
| Set B P@3 | 56% | ≥58% (슬랭 중첩 효과) |
| Set A P@3 | 79% | ≥79% (회귀 없음) |
| 전체 P@3 | 68.0% | ≥72% (작업 1+2+3 합산) |
| 매핑 성공률 | — | ≥84% (42/50) |
