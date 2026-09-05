# portrait-autorig

`Production-ready Portrait/Assembly Bundle → derived rig parts + animated portrait rig`

이 저장소는 [`seethrough-portrait`](https://github.com/prentice7725/seethrough-portrait)가
생성하는 버전 관리 파일 계약을 소비합니다. See-Through, torch, diffusers에 대한
런타임 또는 Python 의존성은 없습니다.

## 데스크톱 GUI (권장)

Windows에서 프로젝트를 clone/install한 뒤 다음 파일을 더블클릭합니다.

```text
portrait_autorig_gui.pyw
```

GUI는 실행 즉시 **RIG 만들기** 화면을 엽니다. Portrait Bundle 또는 Composer
Assembly Bundle을 Rig Bundle로 컴파일하며, 표정과 VariantSet authoring은 Composer가 담당합니다.
따라서 AutoRig의 기본 화면에서는 표정 도너를 별도로 선택하지 않습니다.
빌드가 성공하면 생성된 Rig manifest를 로컬 preview viewer로 자동 연결하며,
`뷰어 열기` 버튼으로 다시 열 수 있습니다. `결과 폴더 열기`는 파일 탐색기에서
출력물을 확인할 때 사용합니다.

Rig builder가 지원하는 기능:

- 단일 Portrait/Assembly Bundle 빌드
- 폴더 내 `*.portrait` Bundle 일괄 빌드
- 자동 출력 경로 (`A001.portrait` → 같은 위치의 `A001.rig`)
- 선택적 재귀 일괄 검색
- 레거시 입력 호환
- 선택적 뒷머리 움직임 완화
- 진행률, Portrait별 preflight/rest-fidelity 상태, 빌드 로그
- 생성된 출력 폴더 바로 열기

Composer가 기록한 `variant_sets`와 `expression_presets`는 Assembly Bundle 입력에서
그대로 읽어 Runtime `sprite_swap`/preset binding으로 컴파일합니다. 기존 expression
donor 모듈과 CLI는 이전 Rig Bundle 호환성을 위해 남아 있지만, 새 Composer 기반
워크플로에서는 기본 경로가 아닙니다.

패키지를 설치하면 동일한 런처가 `portrait-autorig-gui` GUI script로 등록됩니다.
GUI 코드는 재사용 가능한 워크플로 함수(`workflow.py`, `expression_workflow.py`)보다
상위 계층에 의도적으로 배치되어 있어, 이후 게임 배포에서도 compiler 로직을
중복하지 않고 동일한 검증 경로를 호출할 수 있습니다.

## 명령줄 (자동화 / 대체 경로)

기존 명령줄 인터페이스도 script와 CI에서 사용할 수 있습니다.

```powershell
python -m portrait_autorig path\to\A001.portrait path\to\A001.rig
```

v1 이전의 flat run directory 입력:

```powershell
python -m portrait_autorig path\to\legacy-run path\to\A001.rig --legacy
```

컴파일된 Rig Bundle을 Spine으로 export:

```powershell
python -m portrait_autorig.spine path\to\A001.rig path\to\spine-project
```

현재 CLI는 Portrait Bundle과 legacy run을 대상으로 합니다. Composer Assembly Bundle은
동일한 compiler API의 `compile_assembly_bundle()`/`compile_assembly_asset()`로 컴파일합니다.
Assembly 입력은 Composer가 기록한 `composition.draw_order`, `reference.png`, VariantSet,
RigIntent를 그대로 사용합니다.

단일 빌드의 입력 폴더명은 `.portrait` suffix를 요구하지 않습니다. 내부
`manifest.json`의 `format`과 각 Bundle reader가 검사하는 canonical layer/assembly
contract, canvas 정보와 실제 layer 파일을 읽어 유효성을 검사합니다. 일괄 빌드의
자동 검색은 기존 호환성을 위해 `*.portrait` 명명 규칙을 사용합니다.

Portrait Bundle 입력은 반드시 `canonical_stage=production_repaired`를 선언해야
합니다. 일반 compiler는 입력을 다시 repair하지 않습니다. `--legacy` adapter는
이전 run을 위해서만 고정된 호환성 repair를 수행합니다.

컴파일 결과에는 Rig Bundle manifest에 별도의 `rig_preflight` 결과가 기록됩니다.
`READY`는 기본 rig 핵심 semantic을 사용할 수 있음을 뜻하고, `READY_WITH_DERIVATION`은
보수적인 rig 전용 semantic을 복구했음을 뜻합니다. `DEGRADED`는 정적 portrait는
유효하지만 하나 이상의 animation capability를 사용할 수 없음을 뜻하며,
`INCOMPATIBLE`은 핵심 `head`/`face` semantic이 없음을 뜻합니다. 이 판정은
Portrait Bundle의 정적 유효성을 변경하거나 다시 평가하지 않습니다.

`eyewhite`가 없으면 compiler는 iris anchor 기반 눈 영역에서 `original`, `head`,
`face`를 비교해 양쪽 sclera를 rig working copy 안에서 파생할 수 있습니다. 양쪽이
모두 confidence 검사를 통과한 경우에만 fallback을 적용하고, double draw를 막기 위해
승인된 영역을 working `head`에서 제거하며, provenance를
`derived_semantics.eyewhite`에 기록합니다. canonical Portrait Bundle 파일은 절대
수정하지 않습니다. Composer Assembly가 좌우 눈을 suffix 없는 한 장의 variant로
보내고 eye anchor를 생략한 경우에는 variant alpha의 두 connected component에서
`anchors.eye_left/right`와 `eye_opening.l/r`를 보존하여 blink가 전체 crop bbox가
아닌 각 눈 socket에 대해 수행되도록 합니다.

compiler는 Bundle manifest의 layer로부터 canonical reference를 다시 만들고, cropped
rig를 motion=0으로 렌더링한 뒤 `rest_fidelity` 아래에 비교 결과를 기록합니다
(`mae`, alpha error, bad-pixel ratio, percentiles, maximum error, changed visibility).
Remainder subdivision은 motion owner가 바뀌어도 canonical back-plane draw order를
유지하며, crop 과정에서 희미한 alpha edge도 보존합니다. `fail` 결과는 compile을
중단하고, 정적 pose를 변경하는 semantic 파생은 되돌린 뒤 `DEGRADED`로 보고합니다.

Assembly Bundle의 `variant_sets`는 Rig Manifest의 `visibility` phase에 명시적인
`sprite_swap` entry로 컴파일됩니다. Composer instance ID는 semantic tag와 생성된
rig part를 포함한 `member_bindings`에 그대로 보존됩니다. Runtime은 각 set의
`default`에서 시작하며, Composer의 `active` member는 reference pose 검증에만 사용되고
둘이 다르면 경고가 기록됩니다. `expression_presets`는 여러 set의 member를 원자적으로
선택합니다. 기본 transition policy는 `discrete`이며, Rig Manifest에
`transition: "crossfade"`가 명시된 경우에만 `crossfade`를 사용합니다. 현재 Composer
authoring API는 exclusive VariantSet과 preset을 작성하고, crossfade 선택은 manifest
계약을 통해 전달됩니다. `state_groups`가 있으면 선택한 상태의 여러 member가 함께
보이고, 없으면 선택한 member 하나만 보입니다. 잘못된 member mapping은 compile을
실패시킵니다. `eye_closed`/`mouth_open` 같은 Composer donor semantic은 새 표면이
아니므로 원본 eye/mouth의 `head` 그룹과 depth plane을 공유해 Auto Idle에서도
얼굴과 함께 움직입니다.

Assembly 입력 계약은 Composer `portrait-assembly-v0.2` 스키마를
upstream commit `682f25e`에 고정해 vendoring합니다
([vendored schema](portrait_autorig/schemas/portrait-assembly-v0.2.schema.json)).
Assembly load 시 format/version, canvas, draw order, instance→asset 참조를
검증합니다. 원본 schema는 수정하지 않고 그대로 보관하며, compiler 출력의
`source.assembly_schema`에 vendor, upstream commit, schema id와 pin을 기록합니다.

P0-H에서 `ParamEyeBallX/Y`는 독립 `iridesl`/`iridesr`를 우선 움직이는 보수적인
`gaze` deformer로 컴파일됩니다. 독립 iris가 없고 coarse eye layer만 있으면
Capability Report가 `degraded`로 기록됩니다. `visibility_curve`는 대상 part의
기존 visibility와 VariantSet alpha에 곱해지며, 여러 curve도 곱셈으로 합성됩니다.
Runtime은 manifest의 `evaluation.phases` 순서대로 driver/deformer/constraint 단계를
방문하고, v0.1 `motion`은 호환성 adapter로만 사용합니다.

브라우저에서 [`preview/index.html`](preview/index.html)을 열고 Rig Bundle directory를
선택하면 head turn, tilt, breath, blink, gaze를 테스트할 수 있습니다.

P1 mesh 경로는 `contour_tags`로 선택할 수 있으며 disconnected alpha의
`island_policy`를 `separate`(기본), `connect_nearest`, `largest_only`, `reject` 중에서
지정합니다. 기본 `separate`는 component별로 triangulate하여 섬 사이에 임의의
삼각형 bridge를 만들지 않습니다. `build_rig`/compiler의 `island_policy` 인자로
같은 정책을 전달할 수 있습니다.

Contour hair part에는 선택적으로 `strand_topology`가 붙습니다. 이 기록은
connected mesh component, prominent bottom tip, 그리고 합이 1이 되도록 정규화한
overlapping curtain-column weight를 포함합니다. topology 생성 자체는 물리를
수행하지 않으며, opt-in `physics.strand_driver`가 해당 topology를 secondary
단계에서 소비합니다.
`portrait_autorig.constraints`의 `clip_mask_spec`와 `boundary_stitch_spec`은
각각 source→targets mask와 2개 이상 참여자를 갖는 N-way stitch를 검증해
`constraints` manifest contract로 내보냅니다.

현재 P1/P2 상태는 다음과 같습니다.

P1은 위 항목과 parity/QA gate를 충족하여 `CLOSED/FROZEN` 상태입니다.

- 완료: contour-aware mesh(P1-A), mesh quality QA(P1-B), island policy(P1-C),
  motion-aware density(P1-D), strand topology, clip-mask contract, N-way
  boundary-stitch contract, strand partition QA, constraints-phase dispatch 및
  GPU pixel-level clip/stencil backend
- P2 진행: deterministic fixed-step core(`resetPhysics`, `warmupPhysics`,
  `stepPhysicsFixed`), non-finite rollback, `StrandSpringDriver`,
  `UpperTorsoSecondaryDriver`와 `soft`/`firm_bounce`/`springy` profiles를
  추가했고, opt-in `physics` manifest block과 preview fixed-tick loop에
  연결했습니다. `translation`/`angle`/`velocity`/`acceleration`/`impulse`
  input mode를 지원합니다. strand output은 `strand_spring` secondary
  operation으로 hair topology에 적용되고, torso output은 별도 uniform 이동
  없이 Composer-authored `local_soft_field`의 lobe/lock weights를 통해
  적용됩니다. physics manifest preflight와 capture reset/warmup golden QA도
  추가했습니다. 남은 P2는 계약을 바꾸지 않는 corpus 기반 production driver
  tuning이며, 현재 profile 값은 `EXPERIMENTAL`로 관리합니다. 프로파일 envelope는
  `node preview/check_physics_tuning.mjs`로 재현할 수 있습니다.

Physics는 manifest에서 명시적으로 opt-in합니다. 예시는 다음과 같습니다.

```json
{
  "physics": {
    "config": { "update_hz": 60, "reference_scale": 768 },
    "strand_driver": {
      "input_mode": "translation",
      "strands": [
        { "strand_id": "strand_0", "length": 2, "mass": 1, "geometry_factor": 1 }
      ]
    },
    "upper_torso_driver": {
      "input_mode": "translation",
      "profile": "soft",
      "translation_gain": 1.0,
      "angle_gain": 0.25
    }
  }
}
```

`upper_torso_driver`의 결과는 기존 `local_soft_field`에 합쳐지므로
two-lobe/center/neckline/shoulder lock과 author strength가 유지됩니다. physics
block이 없거나 driver가 비활성화되면 기존 rest reference 경로를 그대로 사용합니다.

Composer가 authoring한 `upper_torso_secondary`의 lobe 중심/반경은 target instance
정규화 좌표입니다. Assembly compile은 이를 `coordinate_space:
"canvas_normalized"`로 manifest에 표시하고, preview는 cropped topwear bbox로
재정규화하지 않습니다. 따라서 Composer overlay와 Rig overlay가 같은 캔버스 위치를
가리키며, AutoRig가 별도의 가슴 영역을 다시 추정하지 않습니다.

주요 회귀 검증은 다음 명령으로 재현할 수 있습니다.

```powershell
python -m pytest -q
node preview/check_deformation.mjs
node preview/check_reference_parity.mjs
node preview/check_capture_physics.mjs
node preview/check_physics_tuning.mjs
```

테스트 의존성에는 원본 Composer schema를 직접 검증하기 위한 `jsonschema`가 포함되어
있으며, 일반 runtime은 외부 Composer 또는 `seethrough_engine`를 import하지 않습니다.
휴리스틱의 계약/실험 구분은 [`docs/HEURISTIC_REGISTRY.md`](docs/HEURISTIC_REGISTRY.md)에
기록하며, 최적화 runtime과 독립 CPU oracle의 parity는
`node preview/check_reference_parity.mjs`로 확인합니다.

원본 feasibility study와 측정된 motion limit은
[`docs/PORTRAIT_AUTO_RIG_FEASIBILITY_v0.1.md`](docs/PORTRAIT_AUTO_RIG_FEASIBILITY_v0.1.md)에
보존되어 있습니다.
