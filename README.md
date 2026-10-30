# Digimart Free Monitor (hourly, PC-independent)

Digimart 신규 매물을 **GitHub Actions**에서 매시간 감시합니다. 맥북/PC를 켜둘 필요가 없습니다. 디지마트 직접 요청이 Cloudflare 403으로 차단되어, 무료 공개 **Jina Reader** (https://r.jina.ai/) 경유 수집으로 바꿨습니다. Firecrawl 유료 요금이나 API 키는 사용하지 않습니다.

## 검색 조건

- 검색어: Tyler / Gibson / PRS / Fender / Nord / Helix / Quad Cortex / Fractal
- 디지마트의 OR 연산자로 검색어를 통합한 검색 1회, 등록일 최신순, 최대 100개 결과
- 100,000엔 초과 ~ 1,000,000엔 미만
- 기존 `monitor.allowed()` 필터 재사용: Fender USA/American/Custom Shop 중심, Arai Kazuki 예외; Gibson에서 Epiphone/Orville 제외; 케이스·가방 단독 품목 제외
- 기존 `data/seen.json`의 DS 상품 ID 중복 제거 기록을 보존
- 첫 번째 정상 실행은 기준점을 생성하고 알림하지 않음. 다음 실행부터 새 상품만 GitHub Issue 생성

## 실행과 알림

- 자동 실행: **매시간 23분 (UTC/KST 모두 각 시간의 23분)**
- 실행 결과: [GitHub Actions](https://github.com/JUNHYUK-TECH/digimart-monitor/actions)
- 새 매물이 있으면 GitHub Issue를 만들고 저장소 소유자를 `@JUNHYUK-TECH`로 멘션 및 담당자로 지정
- **iPhone**: GitHub 모바일 앱에 로그인하고, 이 저장소의 알림(담당자 지정/멘션)을 푸시로 허용해야 합니다. 실제 신규 매물 발생 전까지 iPhone 푸시 수신은 별도 검증이 필요합니다.
- 수동 테스트: Actions -> Digimart Free Monitor -> Run workflow -> `diagnostic=true` (저장/이슈 생성 없음)
- 수동 실제 감시: `diagnostic=false`; 첫 정상 실행 기준점 이후 새 매물만 이슈 생성

## 제한과 안전 장치

- 통합 검색 결과 **상위 100개만** 확인하므로 키워드별 모든 신상품을 보장하지 않으며, 순위 밖으로 밀려난 매물은 놓칠 수 있습니다.
- Jina Reader는 무료 공개 서비스지만 속도 제한, 캐시, 일시적 응답 오류/차단이 생길 수 있습니다. 최신성을 100% 보장하지 않습니다.
- Jina 응답에 상품 ID가 없거나 파싱 비율이 비정상적으로 낮으면 Actions가 실패합니다. 이때 `data/seen.json`은 변경하지 않습니다.
- 정상 수집 시 `data/latest.json`, `data/seen.json`, `data/jina_initialized.json`을 저장합니다.
- 기존 `monitor.py` (Playwright 기반)와 관련 테스트는 롤백 용도로 보존하지만, **현재 GitHub Actions에서는 실행하지 않습니다**.

## 로컬 진단

```bash
python -m pip install -r requirements.txt
python jina_monitor.py --diagnostic
python -m unittest discover -s tests -v
```
