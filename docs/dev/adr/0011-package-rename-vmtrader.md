# ADR-0011: 패키지·배포명을 `qstrader`에서 `vmtrader`로 개명한다

| 항목 | 내용 |
| --- | --- |
| 상태 | **채택됨 (Accepted)** — 본 커밋에서 시행 |
| 작성일 | 2026-08-20 |
| 맥락 | KIS 라이브 브로커 Phase 1 착수 직전 ([spec/kis-broker-design.md](../spec/kis-broker-design.md) §9) |
| 관련 요구 | NFR-4 (백테스트 무회귀) |

## 맥락

이 저장소는 [QSTrader](https://github.com/mhallsmoore/qstrader)(MIT, Michael Halls-Moore / QuantStart)의 포크다. 임포트명·배포명이 모두 `qstrader`인 채로 자체 릴리스(0.3.16)를 이어 왔고, KIS 라이브 연동으로 신규 모듈 13개가 이 네임스페이스 아래 추가될 예정이다. 착수 직전에 다음 사실을 실측했다.

| 사실 | 실측값 (2026-08-20) |
| --- | --- |
| 업스트림 활동 | `upstream/master` 대비 **45커밋 앞섬, 0커밋 뒤짐**. 업스트림 최종 커밋 2024-06-24 (`4c59e15`) — 휴면 |
| 배포 메타데이터 | `pyproject.toml`의 `authors`·`maintainers`가 **업스트림(QuantStart) 그대로**인데 버전은 자체 릴리스. 빌드하면 타인을 저자로 표기한 배포물이 된다 |
| PyPI 점유 | `qstrader`는 업스트림이 점유(HTTP 200). `vmtrader`·`vmquant`·`vm-quant-trader`는 미점유(404) |
| 개명 비용 | import 229줄 / 80파일, 살아있는 문서의 경로 참조 38건. 전부 기계적 치환 |
| 루트 README | 설치 안내가 `pip install qstrader`, 이슈 링크가 업스트림 저장소 — **따라 하면 업스트림 패키지가 설치된다** |

## 결정

**패키지 디렉터리·임포트명·배포명을 모두 `vmtrader`로 개명한다.**

| 대상 | 변경 |
| --- | --- |
| 패키지 디렉터리 | `qstrader/` → `vmtrader/` (`git mv` — 이력 보존) |
| 임포트 | `from qstrader...` → `from vmtrader...` (229줄) |
| 배포명 | `pyproject.toml` `name = "vmtrader"`, `authors`를 본 저장소 소유자로 정정, `description` 갱신, URL을 본 저장소로 교체하고 업스트림은 `Upstream` 항목으로 귀속 표기 |
| 환경변수 | `QSTRADER_*` → `VMTRADER_*` (`CSV_DATA_DIR`·`OUTPUT_DIR`·`ENV_FILE`) — 외부 의존처 없음을 확인 후 시행 |
| 문서 | 루트 `README.md`와 **살아있는 문서**(`docs/README.md`, `docs/dev/spec/`, `docs/dev/adr/`)의 경로·이름 갱신 |
| 라이선스·귀속 | `LICENSE-MIT` 및 그 고지는 **불변**. README·`pyproject.toml`에 업스트림 유래를 명시 유지 |

`docs/dev/reports/`의 보고서는 **고치지 않는다** — 작성 시점의 사실을 기록한 불변 스냅샷이므로 당시 이름(`qstrader/…`)을 그대로 둔다.

## 검토한 대안

| 대안 | 기각 사유 |
| --- | --- |
| 1. 현상 유지 | `pip install qstrader`가 업스트림을 설치하는 상태가 지속되고, 배포 메타데이터의 저자 오기가 남는다. 코드도 배포도 타인 이름이다 |
| 2. 배포명만 개명 (임포트는 `qstrader` 유지) | 정체성이 절반만 정리된다. 저장소·배포·임포트가 서로 다른 이름을 갖는 상태가 영구화된다 |
| 3. lab 네임스페이스 합류 (`vmquant.trader`) | 브랜드는 통일되나 [ADR-0003](0003-port-lab-code.md)이 lab과의 관계를 "의존이 아니라 이식"으로 못 박았는데 네임스페이스 공유는 그 결정과 신호가 어긋난다. src 레이아웃 개편 리스크도 얹힌다 |

## 근거

1. **업스트림 병합 가치가 0이다.** 45커밋 앞서고 0커밋 뒤진 휴면 저장소이므로, `qstrader` 이름을 유지할 유일한 실익(상류 변경 수용)이 존재하지 않는다.
2. **어차피 정체성 정리가 필요하다.** 저자 메타데이터가 업스트림 그대로인 상태는 개명 여부와 무관하게 고쳐야 한다.
3. **지금이 가장 싼 시점이다.** Phase 1에서 신규 모듈 13개가 들어오면 개명 대상이 그만큼 늘고, 문서의 파일:줄 인용도 전부 재작업 대상이 된다.

## 결과

- **파괴적 변경**: `import qstrader`를 쓰는 외부 코드는 깨진다. 본 저장소를 라이브러리로 쓰는 외부 의존처는 확인 결과 없다(lab 포함).
- 환경변수도 개명되므로 기존 `.env`는 키 이름을 갱신해야 한다 (`.env.example` 동봉).
- 무회귀 검증: 개명 직후 전체 테스트 **290건 통과** (NFR-4).
- 다음 릴리스는 `vmtrader` 이름으로 나간다. PyPI 배포 시 `vmtrader`를 점유한다.
