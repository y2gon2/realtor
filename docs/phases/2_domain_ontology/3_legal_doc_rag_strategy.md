# 법령 문서 RAG 변환 전략: 2025 주택과 세금

> 작성일: 2026-03-22
> 대상 자료: `data/domain_ontology/raw_data/2025_주택과_세금/docx/` (31개 DOCX 파일)
> 발행처: 국세청·행정안전부

---

## 0. 배경 및 문제 정의

### 0-1. 자료 특성

기존 `data/domain_ontology/parsed/2025_housing_tax.json`은 PDF OCR 방식으로 생성되어 텍스트 품질이 심각하게 훼손된 상태였다 (예: "FHS", "ASO]", "SPAS", "ARIS" 등 다수 아티팩트). **DOCX 파일이 정본**이며 이를 기반으로 재파싱이 필요하다.

이 자료는 유튜브 스크립트 기반 v1/v2 포맷과 근본적으로 다른 세 가지 특수성을 가진다:

| 특수성 | 내용 | 기존 방식의 한계 |
|---|---|---|
| **법적 정밀성** | 세율, 조건, 금액 등 수치는 원문 그대로 보존 필요 | LLM 요약/재해석 불가 |
| **다중파일 연속성** | 5편 구조가 31개 파일에 분산, 일부 편이 여러 파일에 걸쳐 있음 | 파일 단위 독립 처리 불가 |
| **표 중심 구조** | 세율표, 요건표, 계산사례가 핵심 정보 | 텍스트 청킹으로 표 정보 유실 |

### 0-2. 문서 구조

5편 구성, 31개 DOCX 파일로 분할:

| 편 | 주제 | 대상 파일 |
|---|---|---|
| 제1편 | 주택의 취득과 관련된 세금 (취득세) | part0~part4 |
| 제2편 | 주택의 보유와 관련된 세금 (재산세, 종부세) | part5~part9_2 |
| 제3편 | 주택의 임대와 관련된 세금 | part10~part13 |
| 제4편 | 주택의 양도와 관련된 세금 (양도소득세) | part14~part24 |
| 제5편 | 무상이전(증여·상속) 관련 세금 | part25~part30 |

특수 파일: `part8_1`, `part8_2` (종합부동산세 연속), `part9_1`, `part9_2` (연속), `part2_1` (part1 계속)

---

## 1. 출력 목표 (2-Track)

```
DOCX 파일 (31개)
    │
    ▼
[파서] parse_housing_tax_docx.py
    │
    ├──► Track 1: legal_guide 청크 JSON
    │        → [LLM 보강] llm_enrich_housing_tax.py
    │        → [Qdrant 색인] index_legal_docs.py
    │        → Qdrant `legal_docs` 컬렉션 (신규)
    │
    └──► Track 2: [온톨로지 추출] extract_tax_ontology.py
             → ontology_data/entries/tax.json
             → Qdrant `domain_ontology` 컬렉션 (기존, 세금 브랜치 40~60개)
```

---

## 2. 새 doc_type 스키마: `legal_guide`

YouTube 노트용 v1/v2 YAML 포맷과 완전히 별개로 설계.

**핵심 원칙: `content` 필드는 불변 (LLM 접근 금지), `retrieval` 필드만 LLM 생성.**

### 2-1. 스키마 정의

```json
{
  "chunk_id": "ht2025_1_3_1_001",
  "doc_type": "legal_guide",
  "source": {
    "title": "2025 주택과 세금",
    "publisher": "국세청·행정안전부",
    "year": 2025,
    "origin_files": ["2025_주택과_세금_part4.docx"]
  },
  "hierarchy": {
    "part_num": 1,
    "part_title": "제1편 주택의 취득과 관련된 세금",
    "chapter_title": "취득세 중과세",
    "section_title": "다주택자의 주택 유상 취득 중과세"
  },
  "content": {
    "prose": "1주택을 소유하고 있는 1세대가 조정대상지역에 있는 주택을 취득하여 2주택이 되는 경우에는 8%의 세율이 적용된다. 다만, 이사 등의 사유로 일시적 2주택이 되는 경우에는 종전주택을 일정 기간 내에 처분하는 조건으로 1주택 세율이 적용된다.",
    "tables": [
      {
        "caption": "다주택자 적용 세율",
        "markdown": "| 구분 | 세율 |\n|---|---|\n| 조정대상지역 2주택 | 8% |\n| 비조정대상지역 2주택 | 1~3% |\n| 조정대상지역 3주택+ | 12% |\n| 비조정대상지역 3주택+ | 8% |",
        "json_rows": [
          {"구분": "조정대상지역 2주택", "세율": "8%", "비고": "일시적 2주택 제외"},
          {"구분": "비조정대상지역 2주택", "세율": "1~3%", "비고": "표준세율"},
          {"구분": "조정대상지역 3주택+", "세율": "12%", "비고": ""},
          {"구분": "비조정대상지역 3주택+", "세율": "8%", "비고": ""}
        ],
        "row_facts": [
          "조정대상지역 2주택 취득세율: 8% (일시적 2주택 제외)",
          "비조정대상지역 2주택 취득세율: 1~3% (표준세율)",
          "조정대상지역 3주택 이상 취득세율: 12%",
          "비조정대상지역 3주택 이상 취득세율: 8%"
        ]
      }
    ],
    "legal_refs": ["지방세법 제13조의2"]
  },
  "retrieval": {
    "atomic_facts": [
      "조정대상지역에서 2번째 집 취득 시 취득세 8% (일시적 2주택 제외)",
      "조정대상지역 3주택 이상 또는 비조정 4주택 이상 취득세 12%"
    ],
    "hyde_questions": [
      "조정대상지역에서 두 번째 집을 살 때 취득세가 얼마나 나오나요?",
      "다주택자 취득세 중과세율은 어떻게 되나요?",
      "집 두 채 가진 사람이 세 번째 집 살 때 취득세는?",
      "1세대 3주택 취득세율",
      "투기과열지구 취득세 중과"
    ],
    "keywords": ["취득세", "중과세", "다주택자", "조정대상지역", "8%", "12%", "1세대 2주택", "1세대 3주택"],
    "generation_model": "claude-sonnet-4-6",
    "generation_date": "2026-03-22"
  }
}
```

### 2-2. 필드별 LLM 허용 여부

| 필드 | 출처 | LLM 허용 | 제약 |
|---|---|---|---|
| `content.prose` | DOCX 텍스트 | ❌ | 원문 그대로 |
| `content.tables[].markdown` | DOCX 표 | ❌ | 구조 변환만 |
| `content.tables[].json_rows` | DOCX 표 | ❌ | 구조 변환만 |
| `content.tables[].row_facts` | DOCX 표 행 | ⚠️ 제한적 | 수치·조건은 원문 그대로, 문장 형태만 LLM |
| `content.legal_refs` | DOCX 텍스트 | ❌ | 정규식 추출 |
| `retrieval.atomic_facts` | content 전체 | ⚠️ 제한적 | **수치는 원문 인용만 허용** |
| `retrieval.hyde_questions` | 청크 전체 | ✅ | 자유 생성 |
| `retrieval.keywords` | 청크 전체 | ✅ | 자유 추출 |

---

## 3. 표(Table) 처리 전략: Hybrid

세 가지 표현을 동시 저장:

| 필드 | 용도 | 검색 역할 |
|---|---|---|
| `markdown` | LLM 프롬프트 전달 | 컨텍스트 검색 (넓은 매칭) |
| `json_rows` | 프로그래밍 검증, row_facts 생성 입력 | 구조 데이터 |
| `row_facts` | 행 단위 원자 사실 | **숫자 검색 high-precision** |

`row_facts`가 핵심: "3주택자 취득세율"처럼 구체적인 수치 질의가 테이블 행에 직접 매칭됨.

**기술적 주의사항:**
- `doc.paragraphs`와 `doc.tables`를 각각 flat list로 순회하면 단락과 표의 **상대 순서가 깨짐**
- **`doc.element.body` XML 요소 직접 순회 필수** (표 캡션 단락과 표의 연결 보존)
- 병합셀: python-docx는 병합셀 텍스트를 반복 노출 → 인접 셀 비교로 중복 제거

---

## 4. 파일 순서 매핑 (PART_MANIFEST)

31개 파일의 편 귀속 및 is_continuation 확정이 구현 전 필수 작업.

```python
PART_MANIFEST = [
    # (stem, part_num, is_continuation)
    ("2025_주택과_세금_part0",         0, False),  # 표지·목차
    ("2025_주택과_세금_part1",         1, False),  # 제1편 취득세 시작
    ("2025_주택과_세금_part2_1",       1, True),   # 제1편 계속
    ("2025_주택과_세금_part3",         1, True),
    ("2025_주택과_세금_part4",         1, True),
    ("2025_주택과_세금_part5",         2, False),  # 제2편 보유세 시작
    ("2025_주택과_세금_part6",         2, True),
    ("2025_주택과_세금_part7",         2, True),
    ("2025_주택과_세금_part8_1",       2, True),   # 종합부동산세 1
    ("2025_주택과_세금_part8_2",       2, True),   # 종합부동산세 2 (continuation)
    ("2025_주택과_세금_part9_1",       2, True),
    ("2025_주택과_세금_part9_2",       2, True),
    ("2025_주택과_세금_part10",        3, False),  # 제3편 임대소득세 시작
    ("2025_주택과_세금_part11",        3, True),
    ("2025_주택과_세금_part12",        3, True),
    ("2025_주택과_세금_part13",        3, True),
    ("2025_주택과_세금_part14",        4, False),  # 제4편 양도소득세 시작
    ("2025_주택과_세금_part15",        4, True),
    ("2025_주택과_세금_part16",        4, True),
    ("2025_주택과_세금_part17",        4, True),
    ("2025_주택과_세금_part18",        4, True),
    ("2025_주택과_세금_part19",        4, True),
    ("2025_주택과_세금_part20",        4, True),
    ("2025_주택과_세금_part21",        4, True),
    ("2025_주택과_세금_part22",        4, True),
    ("2025_주택과_세금_part23",        4, True),
    ("2025_주택과_세금_part24",        4, True),
    ("2025_주택과_세금_part25",        5, False),  # 제5편 증여·상속세 시작
    ("2025_주택과_세금_part26",        5, True),
    ("2025_주택과_세금_part27",        5, True),
    ("2025_주택과_세금_part28",        5, True),
    ("2025_주택과_세금_part29",        5, True),
    ("2025_주택과_세금_part30",        5, True),
]
```

---

## 5. 구현 파일 목록

| 단계 | 파일 | 입력 | 출력 |
|---|---|---|---|
| 파서 | `scripts/parse_housing_tax_docx.py` | 31개 DOCX | `parsed/2025_housing_tax_v2_raw.json` |
| LLM 보강 | `scripts/llm_enrich_housing_tax.py` | `*_raw.json` | `parsed/2025_housing_tax_v2.json` |
| 온톨로지 추출 | `scripts/extract_tax_ontology.py` | `*_v2.json` | `ontology_data/entries/tax.json` |
| Qdrant 색인 | `codes/embedding/index_legal_docs.py` | `*_v2.json` | Qdrant `legal_docs` 컬렉션 |

---

## 6. 검증 방법

1. **파서 품질**: `--diagnostic` 모드에서 섹션 수(200~250개), OCR 아티팩트 부재 확인
2. **수치 무결성**: `verify_atomic_facts()` — atomic_fact 내 수치가 원문에 존재하는지 자동 검증
3. **커버리지**: 5편 모두 포함 확인, part8_1+part8_2 병합 정상 처리 확인
4. **검색 품질**: "조정대상지역 2주택 취득세" 등 대표 질의로 Qdrant 검색 결과 spot-check
5. **온톨로지 연동**: `source_chunk_id` 링크로 Track 1↔Track 2 참조 무결성 확인

---

## 7. 도메인 온톨로지 세금 브랜치 예상 엔트리

| 편 | 세금 유형 | 예상 Level 3 항목 수 |
|---|---|---|
| 제1편 취득 | 취득세, 취득세 중과, 취득세 감면, 자금출처 확인 | 10~12개 |
| 제2편 보유 | 재산세, 종합부동산세, 1세대1주택 특례 | 10~12개 |
| 제3편 임대 | 주택임대소득, 분리과세, 종합과세, 등록임대사업자 감면 | 8~10개 |
| 제4편 양도 | 양도소득세, 비과세, 장기보유특별공제, 다주택 중과 | 14~16개 |
| 제5편 증여·상속 | 증여세, 상속세, 이월과세, 부담부증여 | 8~10개 |
| **합계** | | **50~60개** |

---

## 8. 핵심 파일 참조

| 파일 | 역할 |
|---|---|
| `scripts/parse_hf_housing_finance.py` | DOCX 파싱 패턴 참고 (element.body 순회로 업그레이드) |
| `codes/embedding/chunker.py` | 3종 청크 타입 패턴(prose/fact/hyde), Chunk 데이터클래스 참고 |
| `planning/docs/phases/2_domain_ontology/2_domain_ontology_plan.md` | 온톨로지 엔트리 스키마 (섹션 2-2) 준수 |
| `data/domain_ontology/raw_data/2025_주택과_세금/docx/` | 31개 소스 DOCX 파일 |
