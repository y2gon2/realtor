# Contextual Retrieval 맥락 Prefix 생성 — 상세 작업 계획

> 작성일: 2026-03-26
> 선행 문서: `5_phase2_search_test_report.md`, `6_search_improvement_research.md` §1
> 목적: domain_ontology + legal_docs 컬렉션에 Contextual Retrieval 기법 적용

---

## 0. 배경 및 동기

### 해결 대상 약점 (Phase 2 검색 테스트 기준)

| 약점 | 현상 | 현재 수치 | 목표 |
|------|------|----------|------|
| **W2**: 추상적 구어체 질의 | "집 살 때 세금" → "취득세"가 4위 (Top-1이 아님) | Top-1 score 0.611 | 0.70+ |
| **W4**: 전체 Top-1 점수 미흡 | Dense 단일 벡터 의존, 평균 0.5~0.6 | Precision@3 80% | 85%+ |

### Contextual Retrieval이란?

Anthropic이 2024년에 발표한 기법. 각 청크를 임베딩하기 **전에**, LLM을 사용해 해당 청크가 문서 전체에서 어떤 맥락에 위치하는지를 1~2문장으로 요약한 prefix를 붙인다.

**예시 — 온톨로지 엔트리 "취득세":**

```
[변환 전 — 현재]
임베딩 텍스트: "취득세 | 다주택자 취득세 중과세율, 집 여러 채 살 때 취득세 |
1세대 2주택(조정대상지역) 취득 시 8% 중과..."

[변환 후 — Contextual Retrieval 적용]
임베딩 텍스트: "부동산을 매수하거나 상속·증여받을 때 발생하는 거래세로,
일반인들이 '집 살 때 세금', '아파트 사면 세금 얼마' 등으로 검색하는 개념이다.
세금 분야의 핵심 용어로 양도소득세·재산세와 함께 부동산 3대 세금을 구성한다. |
취득세 | 다주택자 취득세 중과세율..."
```

### 기대 효과 (Anthropic 벤치마크)

| 조합 | 검색 실패 감소율 |
|------|----------------|
| Contextual Embeddings 단독 | **-35%** |
| + BM25 (Rank Fusion) | **-49%** |
| + Reranking | **-67%** |

### 참고 문헌

- Anthropic, "Contextual Retrieval" (2024) — https://www.anthropic.com/news/contextual-retrieval
- Anthropic, "Prompt Caching" — https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
- DataCamp Contextual Retrieval Tutorial — https://www.datacamp.com/tutorial/contextual-retrieval-anthropic

---

## 1. 아키텍처 결정

### 1-1. `script_override` 방식 채택 (커스텀 Python 스크립트)

기존 `claude_preprocess.sh`는 **파일 단위 1:1 변환** 패턴 (source_dir에서 파일 선택 → 프롬프트 조립 → 결과를 output_dir에 저장). Contextual Retrieval은 이 패턴에 맞지 않음:

| 항목 | `claude_preprocess.sh` 패턴 | Contextual Retrieval 요구 |
|------|---------------------------|--------------------------|
| 처리 단위 | 파일 1개 | JSON 내부 엔트리/청크 1개~15개 |
| 입력 맥락 | 파일 내용 + reference_docs | 브랜치 요약 + 계층 구조 + 인접 항목 |
| 출력 형태 | 새 파일 (source → output) | 기존 데이터에 prefix 필드 추가 (별도 파일) |
| 진행 추적 | 파일 존재 여부 | 배치별 체크포인트 |

→ `enrich_aliases.py` + `enrich_aliases_cron.sh` 패턴을 따름 (`script_override`)

### 1-2. Prefix 저장 전략: 원본 분리

원본 JSON을 수정하지 않고 별도 디렉토리에 저장:

```
ontology_data/contextual_prefixes/
  _branch_summaries.json              # 브랜치별 요약 (사전 생성, 1회)
  tax.json                            # {"tax_acquisition": "prefix...", ...}
  auction.json                        # ...
  contract.json
  land.json
  loan.json
  registration.json
  regulation.json
  rental.json
  reconstruction.json
  subscription.json

data/domain_ontology/parsed/contextual_prefixes/
  2025_housing_tax_v2.json            # {"ht2025_0_0_0_000": "prefix...", ...}

ontology_data/ctx_checkpoints/        # 배치별 체크포인트
  tax_0000.json                       # 배치 결과 캐시
  ...
  legal_0000.json
  ...
```

**분리 이유:**
- 원본 데이터 무결성 보장 (장시간 배치 처리 중 오류 발생 시 안전)
- `index_phase2.py`가 prefix를 선택적으로 로딩 (A/B 테스트 용이)
- prefix 재생성 시 원본 영향 없음
- `enrich_aliases.py`의 `alias_checkpoints/` 패턴과 일관성

---

## 2. 처리 대상 및 규모

### 2-1. domain_ontology (온톨로지 용어)

| 브랜치 | 파일 | 엔트리 수 | 배치 수 (15개/배치) |
|--------|------|----------|-------------------|
| tax | `ontology_data/entries/tax.json` | ~577 | ~39 |
| land | `ontology_data/entries/land.json` | ~744 | ~50 |
| contract | `ontology_data/entries/contract.json` | ~200+ | ~14 |
| auction | `ontology_data/entries/auction.json` | ~150+ | ~10 |
| loan | `ontology_data/entries/loan.json` | ~100+ | ~7 |
| rental | `ontology_data/entries/rental.json` | ~100+ | ~7 |
| reconstruction | `ontology_data/entries/reconstruction.json` | ~100+ | ~7 |
| registration | `ontology_data/entries/registration.json` | ~50+ | ~4 |
| regulation | `ontology_data/entries/regulation.json` | ~50+ | ~4 |
| subscription | `ontology_data/entries/subscription.json` | ~50+ | ~4 |
| **합계** | — | **~2,146** | **~143** |

**prefix 생성 단위**: 엔트리 1개당 1 prefix
**"문서 맥락"**: 브랜치 요약 + 상위 계층 구조 (전체 브랜치 덤프 대신 경량 맥락)

### 2-2. legal_docs (법률 문서)

| 항목 | 값 |
|------|---|
| 소스 파일 | `data/domain_ontology/parsed/2025_housing_tax_v2.json` |
| Base chunks | 213개 |
| 확장 포인트 | 976개 (prose 213 + table_fact 577 + hyde 186) |
| **prefix 생성 단위** | **base chunk 213개** (prose/table_fact가 같은 prefix 공유) |
| 배치 수 | ~27 (8개/배치) |

**"문서 맥락"**: 문서 메타데이터 + part/chapter/section 위치 + 인접 청크 발췌

### 2-3. 총 규모

| 지표 | 값 |
|------|---|
| 총 prefix 생성 대상 | 2,146 + 213 = **2,359개** |
| 총 배치 수 | ~143 + ~27 = **~170 배치** |
| 예상 LLM 호출 | ~170 + 10 (브랜치 요약) = **~180 호출** |
| Cron (4분 간격) 예상 소요 | ~12시간 |
| `--all` 연속 실행 예상 소요 | ~2시간 |
| 예상 비용 | ~2,000 토큰/호출 × 180 ≈ 360K 토큰 (Sonnet: ~$0.5 미만) |

---

## 3. 프롬프트 설계

### 3-0. 브랜치 요약 생성 프롬프트 (사전 작업, 1회)

```markdown
당신은 대한민국 부동산 RAG 시스템 전문가입니다.

아래는 부동산 온톨로지의 '{branch_korean}' 분야에 포함된 용어 계층 구조입니다.
이 분야가 다루는 범위와 핵심 개념을 2~3문장으로 요약하세요.
일반인이 어떤 상황에서 이 분야의 용어를 검색하게 되는지도 포함하세요.

<hierarchy>
세금
  ├ 취득세
  │  ├ 취득세 중과
  │  ├ 취득세 감면
  │  └ 취득세 신고납부
  ├ 양도소득세
  │  ├ 1세대 1주택 비과세
  │  ├ 장기보유특별공제
  │  └ ...
  └ ...
</hierarchy>

요약만 반환하세요 (다른 텍스트 없이).
```

**출력 예시:**
```
세금(tax) 분야는 부동산의 취득·보유·양도 각 단계에서 발생하는 조세를 다룬다.
취득세, 재산세, 종합부동산세, 양도소득세가 핵심이며, 증여세·상속세까지 포함한다.
일반인이 "집 살 때/팔 때/보유할 때 세금"을 검색할 때 관련되는 모든 세금 개념이 이 분야에 속한다.
```

### 3-1. 온톨로지 엔트리 prefix 프롬프트

```markdown
당신은 대한민국 부동산 RAG 시스템의 검색 품질 개선 전문가입니다.

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
분야: {branch_name}
분야 요약: {branch_summary}
상위 계층:
{hierarchy_excerpt}
</branch_context>

아래 각 항목에 대해 contextual_prefix를 생성하세요.

[tax_acquisition]
  용어: 취득세
  카테고리: 세금 > 취득세
  설명 (발췌): 부동산·차량 등 과세대상 물건을 취득한 자가 납부하는 지방세...

[tax_additional_penalty]
  용어: 가산세
  카테고리: 세금
  설명 (발췌): 세법에서 규정하는 의무의 성실한 이행을 확보하기 위하여 그 세법에 의한...

...

JSON 배열로만 응답하세요:
[
  {"id": "tax_acquisition", "contextual_prefix": "부동산을 매수하거나 상속·증여받을 때 ..."},
  {"id": "tax_additional_penalty", "contextual_prefix": "세금 신고·납부 기한을 ..."},
  ...
]
```

### 3-2. 법률문서 청크 prefix 프롬프트

```markdown
당신은 대한민국 부동산 세금 법령 해설서 검색 개선 전문가입니다.

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
[이전 청크 요약] {prev_chunk_excerpt}
[다음 청크 요약] {next_chunk_excerpt}
</surrounding>

아래 각 청크에 대해 contextual_prefix를 생성하세요.

[ht2025_1_1_1_001]
  본문 발췌: 1세대가 1주택을 보유하면서 보유기간 2년 이상인 경우...
  표 포함 여부: 없음
  HyDE 질문: "집 팔 때 세금 안 내도 되나요?", "1주택 비과세 조건은?"

...

JSON 배열로만 응답하세요:
[
  {"chunk_id": "ht2025_1_1_1_001", "contextual_prefix": "《2025 주택과 세금》 ..."},
  ...
]
```

---

## 4. 생성 파일 목록

| 파일 | 유형 | 역할 |
|------|------|------|
| `scripts/contextual_prefix.py` | **신규** | 메인 prefix 생성 스크립트 |
| `codes/cron/contextual_prefix_cron.sh` | **신규** | Cron 래퍼 (lock/log/실행) |
| `codes/cron/config/claude_tasks.yaml` | **수정** | contextual_prefix 태스크 추가 |
| `codes/embedding/index_phase2.py` | **수정** | prefix 로딩 + 임베딩 텍스트 prepend |

---

## 5. `index_phase2.py` 수정 사항

### 5-1. 온톨로지 text 빌드 수정

```python
# 현재 (index_phase2.py, _build_ontology_text 함수):
text = term + "\n" + " | ".join(aliases) + "\n" + description

# 수정 후:
if prefix:
    text = prefix + "\n" + term + "\n" + " | ".join(aliases) + "\n" + description
else:
    text = term + "\n" + " | ".join(aliases) + "\n" + description
```

### 5-2. 온톨로지 인덱싱 함수에 prefix 로딩 추가

```python
# index_domain_ontology() 함수 상단에 추가:
prefixes = {}
prefix_dir = ENTRIES_DIR.parent / "contextual_prefixes"
if prefix_dir.exists():
    for pf in prefix_dir.glob("*.json"):
        if pf.stem.startswith("_"):
            continue
        with open(pf) as f:
            prefixes.update(json.load(f))
```

### 5-3. 법률문서 청크 확장에 prefix 적용

```python
# _expand_legal_chunks() 함수:
# prose 타입: prefix + hierarchy_path + prose
# table_fact 타입: prefix + hierarchy_path + row_fact
# hyde 타입: prefix 적용 안 함 (합성 질의이므로)
```

---

## 6. 실행 순서

| 단계 | 작업 | 명령어 / 도구 | 의존 관계 |
|------|------|-------------|----------|
| **1** | `scripts/contextual_prefix.py` 생성 | 코드 작성 | — |
| **2** | `codes/cron/contextual_prefix_cron.sh` 생성 | 코드 작성 | — |
| **3** | 브랜치 요약 생성 (10개 브랜치, 1회) | `python3 scripts/contextual_prefix.py --gen-summaries` | 1 |
| **4** | 수동 테스트: 온톨로지 1배치 | `python3 scripts/contextual_prefix.py --once --collection ontology` | 3 |
| **5** | prefix 품질 수동 검토 | `ctx_checkpoints/tax_0000.json` 확인 | 4 |
| **6** | 프롬프트 조정 (필요 시) | 프롬프트 수정 → 체크포인트 삭제 → 재실행 | 5 |
| **7** | `claude_tasks.yaml`에 태스크 등록 | YAML 편집 | 6 |
| **8** | Cron 등록 | `./manage_cron.sh install` | 7 |
| **9** | 배치 완료 대기 (~170 배치) | `python3 scripts/contextual_prefix.py --status` | 8 |
| **10** | `index_phase2.py` 수정 | 코드 편집 | 9 |
| **11** | A/B 테스트 (임시 컬렉션) | 테스트 컬렉션에 인덱싱 → 동일 질의 비교 | 10 |
| **12** | 본 컬렉션 재인덱싱 | `python3 codes/embedding/index_phase2.py --force` | 11 확인 후 |

---

## 7. 검증 계획

### Phase A: Prefix 품질 스팟체크

1. tax 브랜치 첫 배치(15개) prefix 수동 검토
2. 확인 항목:
   - 길이: 75~150자 범위 내
   - description과 중복 없음
   - 상황적 맥락 포함 (예: "집을 사거나 상속받을 때 발생하는...")
   - 자연스러운 한국어
   - 검색 연결 다리 역할 ("집 살 때 세금" → "취득세" 연결 가능성)

### Phase B: A/B 임베딩 비교

1. tax 브랜치(577개) + legal_docs를 임시 컬렉션 `domain_ontology_ctx_test`에 prefix 적용 인덱싱
2. `search_test_phase2.py`의 10개 온톨로지 질의를 양쪽에 실행
3. **핵심 비교 지표:**

| 질의 | 현재 Top-1 | 목표 | 측정 |
|------|-----------|------|------|
| "집 살 때 세금 얼마야" | 경감세율 (0.622), 취득세 4위 | 취득세 Top-1 | Top-1 term + score |
| 평균 Top-1 score | 0.611 | 0.70+ | 10개 질의 평균 |
| Precision@3 | 80% (8/10) | 85%+ | 상위 3개 중 관련 결과 비율 |

### Phase C: 전체 회귀 테스트

1. 현재 18개 질의(10 온톨로지 + 8 법률) 결과를 baseline JSON으로 저장
2. 재인덱싱 후 동일 질의 실행
3. 개별 질의 score가 0.05 이상 하락하면 해당 prefix 조사·수정

---

## 8. Cron YAML 태스크 정의

```yaml
  # Task 5: Contextual Retrieval 맥락 prefix 생성
  contextual_prefix:
    enabled: true
    description: "온톨로지+법률문서 contextual prefix 생성 (배치 1개/4분, Sonnet)"
    schedule: "*/4 20-23,0-8 * * *"     # 매 4분마다 (20시~08시)
    script_override: "contextual_prefix_cron.sh"
    source_dir: "ontology_data/entries"
    output_dir: "ontology_data/contextual_prefixes"
    reject_dir: "ontology_data/contextual_prefixes"
    retry:
      max_attempts: 3
      wait_seconds: 60
```

---

## 9. 위험 요소 및 대응

| 위험 | 확률 | 영향 | 대응 |
|------|------|------|------|
| Prefix가 description을 반복 | 중 | prefix 효과 감소 | 프롬프트에 명시적 금지 + 스팟체크 |
| Rate limit 초과 | 중 | 배치 실패 | 3회 재시도 + 30초 대기 (enrich_aliases 패턴) |
| Prefix가 너무 짧거나 김 | 중 | 임베딩 품질 불균일 | 길이 검증 로직 (50자 미만 / 200자 초과 경고) |
| 재인덱싱 후 일부 질의 성능 하락 | 저 | 기존 검색 품질 저하 | A/B 테스트로 사전 감지, 문제 prefix 개별 수정 |
| Claude CLI 바이너리 경로 변경 | 저 | 실행 불가 | `CLAUDE_BIN` 상수 + 존재 확인 |
