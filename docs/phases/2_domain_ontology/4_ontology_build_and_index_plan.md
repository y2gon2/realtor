# Phase 2 완성 계획: 온톨로지 빌드 + 전체 색인

> 작성일: 2026-03-22
> 선행 작업: `3_legal_doc_rag_strategy.md` (2025_housing_tax_v2.json 생성 완료)
> 목표: domain_ontology 컬렉션 + legal_docs 컬렉션 색인 완성

---

## 0. 현재 상태

### 완료된 작업
- `data/domain_ontology/parsed/2025_housing_tax_v2.json` (213청크, LLM 보강 완료)
- `data/domain_ontology/parsed/*.json` — 8개 소스 파싱 완료

### 미완성 작업
- 온톨로지 엔트리 미생성 (브랜치별 JSON 없음)
- Qdrant 컬렉션 미생성 (`domain_ontology`, `legal_docs`)

---

## 1. 색인 대상 컬렉션 설계

### 컬렉션 1: `domain_ontology` (구어체→전문용어 매핑)

**용도**: Phase 2 2단계 검색의 Stage 1 — 사용자 구어체 질의를 전문용어로 매핑

```
입력: ontology_data/entries/*.json (브랜치별 엔트리)
임베딩 텍스트: term + aliases + description (합산 1벡터/엔트리)
목표 포인트 수: 1,000~1,700개
```

### 컬렉션 2: `legal_docs` (법령 원문 검색)

**용도**: 세율·조건·기한 등 정확한 수치 질의에 대한 법령 원문 근거 제공

```
입력: data/domain_ontology/parsed/2025_housing_tax_v2.json (현재)
      + 추후 추가될 법령 문서들
임베딩 텍스트: 청크 타입별 3종
  - prose: 원문 텍스트
  - table_fact: 표 행별 사실
  - hyde: 구어체 질문
현재 포인트 수: 213청크 × ~3 = ~600개
```

---

## 2. Step 5: `build_ontology.py` — 온톨로지 통합 빌드

### 2-1. 입력 소스 매핑

| 소스 파일 | 항목 수 | 대상 브랜치 | 비고 |
|---|---|---|---|
| `nts_tax_terms.json` | 미확인 | 세금 | 국세청 세금 용어사전 |
| `2025_housing_tax_v2.json` | 213청크 | 세금 | atomic_facts에서 용어 추출 |
| `hf_housing_finance_terms.json` | 미확인 | 대출/금융 | HF 주택금융공사 |
| `hug_housing_guarantee_terms.json` | 미확인 | 대출/금융 | HUG 주택도시보증공사 |
| `fss_financial_terms.json` | 미확인 | 대출/금융 | 금융감독원 |
| `applyhome_terms.json` | 미확인 | 청약/분양 | 청약홈 |
| `land_use_terms.json` | 미확인 | 토지/개발 | 토지이용 용어사전 |
| `kar_realestate_terms.json` | 미확인 | 등기/계약 | 공인중개사협회 |

### 2-2. 출력 구조

```
ontology_data/
├── taxonomy.json              ← Level 1~2 계층 정의 (수동 확정 필요)
└── entries/
    ├── tax.json               ← 세금 브랜치 (~50~60개)
    ├── loan.json              ← 대출/금융 브랜치 (~60~80개)
    ├── subscription.json      ← 청약/분양 브랜치 (~30~50개)
    ├── rental.json            ← 임대차 브랜치 (~25~40개)
    ├── auction.json           ← 경매/공매 브랜치 (~20~35개)
    ├── reconstruction.json    ← 재건축/재개발 브랜치 (~25~40개)
    ├── regulation.json        ← 규제/정책 브랜치 (~35~50개)
    ├── land.json              ← 토지/개발 브랜치 (~20~30개)
    ├── registration.json      ← 등기/권리 브랜치 (~25~40개)
    └── contract.json          ← 계약/거래 브랜치 (~20~35개)
```

### 2-3. 처리 흐름

```
[Phase A: taxonomy.json 확정]
  - 2_domain_ontology_plan.md 섹션 2-1의 Level 1~2 체계를 파일로 확정
  - 수동 작업 또는 LLM 보조

[Phase B: 소스별 브랜치 LLM 배치 생성]
  소스 JSON → LLM 프롬프트 →
    - 기존 용어 항목을 온톨로지 엔트리 스키마로 변환
    - aliases 5~10개 생성 (구어체 2개 이상 필수)
    - description 1~2문장 생성
    - source_ref 필드로 원본 소스 연결

  2025_housing_tax_v2.json → 추가 처리:
    - 청크의 section_title + atomic_facts → 세금 개념 추출
    - 추출된 개념을 Level 3 엔트리로 변환
    - source_chunk_id로 legal_docs 청크와 양방향 연결

[Phase C: 중복 제거 및 검수]
  - validator.py: id 중복, parent_id 존재 여부, aliases 최소 수 검증
  - related_terms 연결 확인
```

### 2-4. 엔트리 스키마 (2_domain_ontology_plan.md 섹션 2-2 준수)

```json
{
  "id": "tax_acquisition_multi_surcharge",
  "term": "다주택자 취득세 중과",
  "level": 3,
  "parent_id": "tax_acquisition",
  "category_path": "세금 > 취득세",
  "aliases": [
    "다주택 취득세 중과세율",
    "집 여러 채 살 때 취득세",
    "2주택 취득세 8퍼센트",
    "3주택 취득세 12퍼센트",
    "조정대상지역 취득세 중과",
    "다주택자 취득세 페널티"
  ],
  "related_terms": [
    "tax_transfer_multi_surcharge",
    "regulation_adjustment_zone"
  ],
  "description": "1세대 2주택(조정대상지역) 취득 시 8%, 3주택+(조정) 또는 4주택+(비조정) 취득 시 12% 중과세. 지방세법 제13조의2.",
  "source_ref": "nts_tax_terms",
  "source_chunk_id": "ht2025_1_3_1_xxx"
}
```

### 2-5. 구현 파일

```
scripts/build_ontology.py      ← 메인 빌더 (소스 → entries/*.json)
codes/ontology/schema.py       ← Pydantic 엔트리 모델
codes/ontology/validator.py    ← 검수 도구 (중복/누락/참조 검증)
```

---

## 3. Step 6: `index_phase2.py` — Phase 2 전체 색인

### 3-1. 색인 대상 전체

```
[domain_ontology 컬렉션]
  입력: ontology_data/entries/*.json (Step 5 출력)
  벡터: Dense 1개/엔트리 (term + aliases + description 합산)
  모델: KURE-v1 (기존과 동일)
  예상 포인트: 1,000~1,700개

[legal_docs 컬렉션]
  입력: data/domain_ontology/parsed/2025_housing_tax_v2.json
  벡터: Dense + Sparse (BM25) 각 3종/청크 (prose/table_fact/hyde)
  모델: KURE-v1 + BM25
  예상 포인트: ~600개
```

### 3-2. Qdrant 컬렉션 스펙

**domain_ontology** (기존 컬렉션 확장 또는 재생성):
```python
client.create_collection(
    collection_name="domain_ontology",
    vectors_config={
        "dense": VectorParams(size=1024, distance=Distance.COSINE),
    },
)
# 페이로드 인덱스
# term, level, parent_id, category_path → KEYWORD/INTEGER
```

**legal_docs** (신규 컬렉션):
```python
client.create_collection(
    collection_name="legal_docs",
    vectors_config={
        "dense": VectorParams(size=1024, distance=Distance.COSINE),
    },
    sparse_vectors_config={
        "sparse": SparseVectorParams(index=SparseIndexParams(on_disk=False)),
    },
)
# 페이로드 인덱스
# doc_type, hierarchy.part_num, hierarchy.part_title, source.year,
# chunk_type (prose/table_fact/hyde) → KEYWORD/INTEGER
```

### 3-3. legal_docs 청크 타입별 임베딩 텍스트

| chunk_type | 임베딩 텍스트 구성 | 검색 역할 |
|---|---|---|
| `prose` | `{계층경로}\n\n{prose}` | 개념/설명 검색 |
| `table_fact` | `{계층경로}\n\n{row_fact 1개}` | 수치/조건 정밀 검색 |
| `hyde` | `{hyde_questions 5개 줄바꿈}` | 구어체 질의 매칭 |

### 3-4. 구현 파일

```
codes/embedding/index_phase2.py    ← 통합 색인 스크립트
  ├── index_domain_ontology()      ← domain_ontology 컬렉션 색인
  └── index_legal_docs()           ← legal_docs 컬렉션 색인
```

기존 코드 재사용:
- `codes/embedding/embedder.py` — KURE-v1 임베딩
- `codes/embedding/upserter.py` — Qdrant upsert 로직

---

## 4. 선행 필요 작업: taxonomy.json 확정

Step 5 실행 전 `ontology_data/taxonomy.json`을 수동으로 확정해야 합니다.

```json
{
  "level1": [
    {
      "id": "tax",
      "term": "세금",
      "children": [
        {"id": "tax_acquisition", "term": "취득세"},
        {"id": "tax_property", "term": "재산세"},
        {"id": "tax_comprehensive_property", "term": "종합부동산세"},
        {"id": "tax_transfer", "term": "양도소득세"},
        {"id": "tax_rental_income", "term": "주택임대소득세"},
        {"id": "tax_gift", "term": "증여세"},
        {"id": "tax_inheritance", "term": "상속세"}
      ]
    },
    {
      "id": "loan",
      "term": "대출/금융",
      "children": [
        {"id": "loan_dsr", "term": "DSR"},
        {"id": "loan_ltv", "term": "LTV"},
        ...
      ]
    },
    ...
  ]
}
```

이 파일은 LLM 배치 생성 시 `parent_id`의 기준이 됩니다.

---

## 5. 전체 작업 순서 (요약)

```
[완료] DOCX 파싱 + LLM 보강 → 2025_housing_tax_v2.json

[Step 5-A] taxonomy.json 확정
  → ontology_data/taxonomy.json 생성 (수동 또는 LLM 보조)

[Step 5-B] build_ontology.py 실행
  → 소스 8개 + 2025_housing_tax_v2.json → entries/*.json
  → 체크포인트 방식 (브랜치별 재실행 가능)

[Step 5-C] validator.py로 검수
  → 중복/누락/참조 오류 확인 + 수동 보완

[Step 6] index_phase2.py 실행
  → domain_ontology 컬렉션 색인 (1,000~1,700 포인트)
  → legal_docs 컬렉션 색인 (~600 포인트)

[검증] search_test.py
  → Overlap@10 ≥ 50% (현재 26%)
  → 용어 매칭 Precision@3 ≥ 70%
```

---

## 6. 핵심 참조 파일

| 파일 | 역할 |
|---|---|
| `planning/docs/phases/2_domain_ontology/2_domain_ontology_plan.md` | 온톨로지 스키마 및 전체 설계 (섹션 2-2, 3-3) |
| `planning/docs/phases/2_domain_ontology/3_legal_doc_rag_strategy.md` | legal_docs 청크 스키마 |
| `data/domain_ontology/parsed/2025_housing_tax_v2.json` | 세금 브랜치 1차 소스 |
| `codes/embedding/embedder.py` | KURE-v1 임베딩 (재사용) |
| `codes/embedding/upserter.py` | Qdrant upsert (재사용) |
| `codes/ontology/parse_land_use_dict.py` | 기존 온톨로지 파서 참고 |
