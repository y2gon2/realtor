# Opus 4.6 베이스라인 테스트 결과 요약

실행 일시: 2026-04-01 16:04:02 ~ 2026-04-02 14:33:57
모델: claude-opus-4-6
설정: cooldown=30초, timeout=300초
시스템 프롬프트: "당신은 대한민국 부동산 전문 상담사입니다. 한국어로 답변하세요. 구체적이고 실용적으로 답변하세요."

---

## 전체 통계

| 항목 | 값 |
|------|------|
| 총 질문 수 | 761개 |
| 오류 | 0개 |
| 후속 제안 수락 | 315건 |
| 총 입력 토큰 | 2,376 |
| 총 출력 토큰 | 1,517,613 |
| 평균 소요시간 | 40,482ms |
| 총 CLI 비용 | $63.36 |
| 총 추정 API 비용 | $113.86 |
| 총 실행시간 | 513분 |

---

## Part별 통계

### Part A
| 항목 | 값 |
|------|----|
| 질문 수 | 100개 |
| 오류 | 0개 |
| 후속 수락 | 47건 |
| 입력 토큰 | 330 |
| 출력 토큰 | 128,803 |
| 평균 소요시간 | 28,917ms |
| CLI 비용 | $4.39 |
| 추정 API 비용 | $9.67 |

### Part B
| 항목 | 값 |
|------|----|
| 질문 수 | 564개 |
| 오류 | 0개 |
| 후속 수락 | 246건 |
| 입력 토큰 | 1,755 |
| 출력 토큰 | 1,140,562 |
| 평균 소요시간 | 40,777ms |
| CLI 비용 | $48.56 |
| 추정 API 비용 | $85.57 |

### Part C
| 항목 | 값 |
|------|----|
| 질문 수 | 12개 |
| 오류 | 0개 |
| 후속 수락 | 4건 |
| 입력 토큰 | 36 |
| 출력 토큰 | 16,165 |
| 평균 소요시간 | 29,158ms |
| CLI 비용 | $0.53 |
| 추정 API 비용 | $1.21 |

### Part D
| 항목 | 값 |
|------|----|
| 질문 수 | 85개 |
| 오류 | 0개 |
| 후속 수락 | 18건 |
| 입력 토큰 | 255 |
| 출력 토큰 | 232,083 |
| 평균 소요시간 | 53,734ms |
| CLI 비용 | $9.87 |
| 추정 API 비용 | $17.41 |

---

## 토큰 사용량 참고사항

> CLI가 보고하는 `input_tokens`는 사용자 메시지만 카운트하며, 시스템 프롬프트 및 CLI 내부 컨텍스트는 별도 처리됩니다.
> 실제 API 호출 시 입력 토큰은 시스템 프롬프트 + 대화 컨텍스트를 포함하여 훨씬 높습니다.
> `total_cost_usd`는 CLI가 보고한 실제 API 사용량 기반 비용이며, Max 플랜 구독 시 별도 과금되지 않습니다.

---

## 비용 비교 (API 기준 추산)

| 항목 | Opus 4.6 | 비고 |
|------|----------|------|
| 입력 토큰 단가 | $15/1M | |
| 출력 토큰 단가 | $75/1M | |
| 총 출력 토큰 | 1,517,613 | |
| CLI 기준 총 비용 | $63.36 | CLI total_cost_usd 합산 |
| 질문당 평균 CLI 비용 | $0.0833 | |

### 질문당 평균 비용 (Part별)

| Part | 질문당 평균 CLI 비용 | 평균 출력 토큰 | 평균 소요시간 |
|------|-------------------|--------------|-------------|
| A (단일) | $0.0439 | 1,288 | 29초 |
| B (연속) | $0.0861 | 2,022 | 41초 |
| C (단일) | $0.0444 | 1,347 | 29초 |
| D (연속) | $0.1162 | 2,730 | 54초 |

---

## RAG 결과와 비교 (Part A+C+D, 197개)

> RAG 결과: `result/` 폴더 (Sonnet + domain_ontology_v2 + legal_docs_v2)

### 응답 특성 비교

| 항목 | RAG (Sonnet) | Opus 4.6 (RAG 없음) |
|------|-------------|-------------------|
| 총 질문 수 | 197개 | 197개 (A+C+D) |
| 문서평가 pass | 21개 (10.7%) | N/A (문서 없음) |
| 할루시네이션 pass | 166개 (84.3%) | 평가 미실시 |
| 평균 소요시간 | 90,868ms (~91초) | 35,717ms (~36초) |
| 평균 LLM 호출 | 3.88회/질문 | 1회/질문 |
| 후속 제안 수락 | N/A | 69건 (35%) |

### 답변 스타일 차이

- **RAG (Sonnet)**: 제공된 문서에서 확인 가능한 내용만 답변, "제공된 자료에서 확인할 수 없습니다" 빈번 (grade=fail 89.3%)
- **Opus 4.6**: 사전 학습 지식 기반으로 구체적이고 상세한 답변 제공, 표/체크리스트/단계별 가이드 형태
- **RAG 장점**: 출처 명시([1][2]...), 법률 조문 근거 제공, 할루시네이션 제어
- **Opus 장점**: 실용적 가이드, 시장 판단 프레임워크 제공, 후속 질문 유도

### 비용 비교

| 시나리오 | 197개 비용 | 질문당 비용 | 비고 |
|---------|-----------|-----------|------|
| RAG (Sonnet, CLI) | ~$6.30 추산 | ~$0.032 | LLM 3.88회/질문 |
| Opus (CLI, 실측) | $14.79 | $0.075 | 후속 포함 |
| RAG (Sonnet, API) | ~$6.30 | ~$0.032 | API 전환 시 동일 |
| RAG (Haiku+Sonnet, API) | ~$3.90 | ~$0.020 | 혼합 최적화 |

---

## 후속 제안 분석

| Part | 질문 수 | 제안 감지 | 수락 | 수락률 |
|------|---------|----------|------|-------|
| A | 100 | 47 | 47 | 47% |
| B | 564 | 247 | 246 | 44% |
| C | 12 | 4 | 4 | 33% |
| D | 85 | 18 | 18 | 21% |
| **합계** | **761** | **316** | **315** | **41%** |

Opus는 약 41%의 질문에서 후속 제안을 했으며, 거의 모두(315/316) 수락되어 추가 답변을 생성했습니다.

---

## 결과 파일 목록

| 파일 | 내용 |
|------|------|
| part_a_singles.md | part_a_singles 결과 |
| part_b_001.md | part_b_001 결과 |
| part_b_002.md | part_b_002 결과 |
| part_b_003.md | part_b_003 결과 |
| part_b_004.md | part_b_004 결과 |
| part_b_005.md | part_b_005 결과 |
| part_b_006.md | part_b_006 결과 |
| part_b_007.md | part_b_007 결과 |
| part_b_008.md | part_b_008 결과 |
| part_b_009.md | part_b_009 결과 |
| part_b_010.md | part_b_010 결과 |
| part_b_011.md | part_b_011 결과 |
| part_b_012.md | part_b_012 결과 |
| part_b_013.md | part_b_013 결과 |
| part_b_014.md | part_b_014 결과 |
| part_b_015.md | part_b_015 결과 |
| part_b_016.md | part_b_016 결과 |
| part_b_017.md | part_b_017 결과 |
| part_b_018.md | part_b_018 결과 |
| part_b_019.md | part_b_019 결과 |
| part_b_020.md | part_b_020 결과 |
| part_b_021.md | part_b_021 결과 |
| part_b_022.md | part_b_022 결과 |
| part_b_023.md | part_b_023 결과 |
| part_b_024.md | part_b_024 결과 |
| part_b_025.md | part_b_025 결과 |
| part_b_026.md | part_b_026 결과 |
| part_b_027.md | part_b_027 결과 |
| part_b_028.md | part_b_028 결과 |
| part_b_029.md | part_b_029 결과 |
| part_b_030.md | part_b_030 결과 |
| part_b_031.md | part_b_031 결과 |
| part_b_032.md | part_b_032 결과 |
| part_b_033.md | part_b_033 결과 |
| part_b_034.md | part_b_034 결과 |
| part_b_035.md | part_b_035 결과 |
| part_b_036.md | part_b_036 결과 |
| part_b_037.md | part_b_037 결과 |
| part_b_038.md | part_b_038 결과 |
| part_b_039.md | part_b_039 결과 |
| part_b_040.md | part_b_040 결과 |
| part_b_041.md | part_b_041 결과 |
| part_b_042.md | part_b_042 결과 |
| part_b_043.md | part_b_043 결과 |
| part_b_044.md | part_b_044 결과 |
| part_b_045.md | part_b_045 결과 |
| part_b_046.md | part_b_046 결과 |
| part_b_047.md | part_b_047 결과 |
| part_b_048.md | part_b_048 결과 |
| part_b_049.md | part_b_049 결과 |
| part_b_050.md | part_b_050 결과 |
| part_b_051.md | part_b_051 결과 |
| part_b_052.md | part_b_052 결과 |
| part_b_053.md | part_b_053 결과 |
| part_b_054.md | part_b_054 결과 |
| part_b_055.md | part_b_055 결과 |
| part_b_056.md | part_b_056 결과 |
| part_b_057.md | part_b_057 결과 |
| part_b_058.md | part_b_058 결과 |
| part_b_059.md | part_b_059 결과 |
| part_b_060.md | part_b_060 결과 |
| part_b_061.md | part_b_061 결과 |
| part_b_062.md | part_b_062 결과 |
| part_b_063.md | part_b_063 결과 |
| part_b_064.md | part_b_064 결과 |
| part_b_065.md | part_b_065 결과 |
| part_b_066.md | part_b_066 결과 |
| part_b_067.md | part_b_067 결과 |
| part_b_068.md | part_b_068 결과 |
| part_b_069.md | part_b_069 결과 |
| part_b_070.md | part_b_070 결과 |
| part_b_071.md | part_b_071 결과 |
| part_b_072.md | part_b_072 결과 |
| part_b_073.md | part_b_073 결과 |
| part_b_074.md | part_b_074 결과 |
| part_b_075.md | part_b_075 결과 |
| part_b_076.md | part_b_076 결과 |
| part_b_077.md | part_b_077 결과 |
| part_b_078.md | part_b_078 결과 |
| part_b_079.md | part_b_079 결과 |
| part_b_080.md | part_b_080 결과 |
| part_b_081.md | part_b_081 결과 |
| part_b_082.md | part_b_082 결과 |
| part_b_083.md | part_b_083 결과 |
| part_b_084.md | part_b_084 결과 |
| part_b_085.md | part_b_085 결과 |
| part_b_086.md | part_b_086 결과 |
| part_b_087.md | part_b_087 결과 |
| part_b_088.md | part_b_088 결과 |
| part_b_089.md | part_b_089 결과 |
| part_b_090.md | part_b_090 결과 |
| part_b_091.md | part_b_091 결과 |
| part_b_092.md | part_b_092 결과 |
| part_b_093.md | part_b_093 결과 |
| part_b_094.md | part_b_094 결과 |
| part_b_095.md | part_b_095 결과 |
| part_b_096.md | part_b_096 결과 |
| part_b_097.md | part_b_097 결과 |
| part_b_098.md | part_b_098 결과 |
| part_b_099.md | part_b_099 결과 |
| part_b_100.md | part_b_100 결과 |
| part_c_singles.md | part_c_singles 결과 |
| part_d_001.md | part_d_001 결과 |
| part_d_002.md | part_d_002 결과 |
| part_d_003.md | part_d_003 결과 |
| part_d_004.md | part_d_004 결과 |
| part_d_005.md | part_d_005 결과 |
| part_d_006.md | part_d_006 결과 |
| part_d_007.md | part_d_007 결과 |
| part_d_008.md | part_d_008 결과 |
| part_d_009.md | part_d_009 결과 |
| part_d_010.md | part_d_010 결과 |
| part_d_011.md | part_d_011 결과 |
| part_d_012.md | part_d_012 결과 |
| part_d_013.md | part_d_013 결과 |
| checkpoint.json | 진행 상태 |
| run.log | 실행 로그 |
| summary.md | 본 요약 문서 |