# PORTRAIT AUTORIG — CHEST SOFT MORPH / BUST MORPH DESIGN v0.1

## 0. 목적

본 문서는 `portrait-autorig`에 **Upper Torso Soft Morph** 계열 변형을 추가하기 위한 설계 아이디어이다.

표면적인 목표는 흔히 말하는 "버스트 모핑"이지만, 시스템 이름과 구조는 더 일반적인 상체 소프트 변형으로 잡는다.

> **기존 호흡 모션을 유지하면서, 상의(topwear) 흉부 영역에 국소적인 볼륨 변화·관성·비대칭을 추가한다.**

핵심은 "새로운 신체 정보를 생성"하는 것이 아니라,

- 이미 그려진 이미 실루엣
- 현재 mesh
- 현재 breathing field
- 현재 body/head/neck motion

위에 **2D local deformation field**를 추가하는 것이다.

---

# 1. 현재 베이스라인

현재 preview/runtime에는 이미 다음이 존재한다.

- body/head/neck group
- per-vertex weight
- neck gradient
- topwear collar gradient
- uniform grid mesh
- breathing vertical ramp
- body의 horizontal chest widening
- head turn / tilt / shell deformation

현재 breathing의 대략:

```text
전체 상체를 연속적인 vertical displacement field로 들어 올리고
body group에는 약한 horizontal widening을 추가
```

하는 구조다.

이 방식은 seam-safe하고 기본 호흡으로는 적절하다.

그러나 현재 chest widening은 **topwear 전체 폭에 가까운 변화**라,

- 실제 흉부 local volume
- 중앙부 고정
- 좌우 soft region
- turn에 따른 비대칭
- secondary motion

을 표현하기 어렵다.

따라서 기존 breathing을 제거하지 않고 그 위에 **local soft morph layer**를 추가한다.

---

# 2. 범위

## 포함

### Phase 1
- 신체 soft region 자동 추정
- topwear local mesh deformation
- symmetric inhale/exhale morph
- center-lock / neckline-lock / side falloff
- rest-pose invariant

### Phase 2
- 좌/우 independent soft zones
- spring / damping 기반 secondary motion
- head/body turn과 약한 coupling

### Phase 3 후보
- garment profile
- multiple torso soft zones
- hand-authored override / mod config
- full-body 대응

## 제외

- 새로운 신체 부위 그림 생성
- semantic layer를 `seethrough`에서 추가 생성
- 실제 3D breast geometry reconstruction
- physics engine 의존성
- 성별/체형을 이미지에서 강제 추론
- 개별 캐릭터 하드코딩

---

# 3. 명칭

코드/manifest에서는 **Bust Morph**보다 다음 명칭을 권장한다.

```text
upper_torso_soft_morph
```

또는 짧게:

```text
chest_soft
```

이유:

- 남성 캐릭터의 흉곽 호흡에도 사용 가능
- 두꺼운 아우터에서는 단순 ribcage expansion으로 사용할 수 있음
- 전신 rig에서는 그대로 확장 가능
- 데이터/모듈 API가 특정 체형에 종속되지 않음

UI에서는만 필요하면:

```text
Chest Soft Morph
```

로 표시한다.

---

# 4. 핵심 원칙

## 4.1 Rest pose invariant

```text
soft_morph = 0
```

일 때 vertex position은 기존 rig와 **완전 동일**해야 한다.

즉 이 기능은 켜도 setup/rest image가 변하면 실패다.

---

## 4.2 Garment-first

현재 입력은 `topwear` 등 옷 레이어다.

따라서 시스템은:

> "가슴 형태"를 추론하지 않고 "의상 흉부 변화 영역"을 추정한다.

이는 특히:

- cardigan
- shirt
- blouse
- sweater

같은 portrait asset에 잘 맞는다.

---

## 4.3 Local deformation only

전체 topwear를 팽창하지 않는다.

변형은 좁은 흉부 field에만 적용한다.

고정해야 할 영역:

- neckline / collar
- 어깨 외곽
- torso bottom
- center placket / zipper / button line (가능할 때)

---

## 4.4 Conservative default

초기 애니메이션값은 기본 강도를 미세해야 한다.

목표는:

```text
"움직인다"
```

이지,

```text
"더 커졌는지 확인 되는지"
```

가 아니다.

---

# 5. 적용 대상

1차 범위 안에서 기본적으로 다음 part만 soft morph 대상으로 한다.

```text
topwear
```

추후 선택:

```text
body_remainder
```

중 topwear 실루엣을 보완하는 영역이 명확할 때만 같은 field를 약하게 적용한다.

다음에는 적용하지 않는다.

- neck
- head
- face
- hair
- eyewhite / eye layers

collar/neckline contact region은 topwear 위에서도 soft morph weight를 0에 가깝게 만든다.

---

# 6. Chest Region 자동 추정

## 6.1 사용 가능한 입력

- `topwear` alpha bbox
- `neck_pivot`
- `body_pivot`
- neck bbox
- canvas size
- topwear visible alpha

추가 semantic 모델을 필요하지 않다.

---

## 6.2 기본 chest frame

`topwear` bbox를:

```text
(x1, y1, x2, y2)
```

라 할 때 대략적인 유효 영역을 만든다.

권장 초기값:

```text
center_x = (x1 + x2) / 2
chest_y  = y1 + 0.30~0.42 * height
```

단 실제 위치는 neckline/neck bbox 아래로 clamp한다.

예:

```text
chest_top >= neck_bottom + local_margin
```

---

## 6.3 Two-lobe region

soft region은 하나의 큰 원이 아니라 좌/우 두 개의 elliptical field로 나눈다.

```text
LEFT SOFT ZONE      RIGHT SOFT ZONE
      ( )                 ( )
          \    lock    /
             center
```

각 ellipse는:

```text
cx = torso_center ± 0.15~0.22 * torso_width
cy = chest_y
rx = 0.22~0.30 * torso_width
ry = 0.16~0.24 * torso_height
```

정도로 시작한다.

실제 값은 canvas/part size에 비례해야 하며 fixed px 하드코딩을 피한다.

---

# 7. Weight Field

각 vertex `(x, y)`에 대해 left/right ellipse의 normalized distance를 계산한다.

개념적으로:

```text
d² = ((x-cx)/rx)² + ((y-cy)/ry)²
```

그리고:

```text
w = smoothstep(1, 0, d²)
```

형태의 falloff를 사용한다.

단 실제 weight는 다음 mask를 추가로 곱한다.

```text
soft_weight
 = ellipse_weight
 × neckline_lock
 × center_lock
 × shoulder_lock
 × bottom_falloff
 × alpha_support
```

---

# 8. Lock Field

## 8.1 Neckline lock

neck/collar seam은 가장 중요한 고정 지점이다.

neck bbox bottom 부근부터 chest 중심까지:

```text
0 → 1
```

로 부드럽게 올라가는 weight를 사용한다.

결과:

- 칼라가 벌어지지 않음
- 목이 흔들리지 않음
- 기존 neck gradient와 충돌하지 않음

---

## 8.2 Center lock

셔츠 단추선, 지퍼, cardigan center line이 좌우로 벌어지면 매우 어색하다.

따라서 torso 중심 근처에는 horizontal displacement를 줄인다.

예:

```text
center_distance = abs(x - center_x)
center_lock = smoothstep(center_lock_width, outer_width, center_distance)
```

즉 중심에서는 0에 가까우며 바깥으로 갈수록 1.

vertical displacement는 center에서도 일부 허용 가능하다.

---

## 8.3 Shoulder lock

topwear bbox 상단 바깥쪽 / 어깨는 local bust morph 때문에 뒤흔들리면 안 된다.

따라서:

- upper corners
- shoulder slopes

에는 강한 falloff를 준다.

---

# 9. Phase 1 Morph Formula

기존 breathing 값:

```text
b = sin(time)
```

를 그대로 사용할 수 있다.

단 soft morph는 `b > 0` inhale에서 좀 더 강하고 exhale에서는 살짝 약하도록 비대칭 curve를 써도 된다.

예:

```text
inflate = max(0, b)
deflate = min(0, b) * 0.35
morph = inflate + deflate
```

초기 버전은 완전 symmetric도 가능하다.

---

## 9.1 Horizontal deformation

left zone:

```text
dx -= strength_x * morph * weight_left
```

right zone:

```text
dx += strength_x * morph * weight_right
```

즉 흉부가 중심에서 바깥쪽으로 아주 약하게 확장된다.

---

## 9.2 Vertical deformation

하단 soft zone에는 아주 미세한 vertical component를 줄 수 있다.

예:

```text
dy += strength_y * morph * lower_bias * weight
```

다만 Phase 1에서는 강도를 horizontal의 20~40% 이내로 제한한다.

기존 breathing이 이미 상체 전체를 위로 들어 올리기 때문이다.

---

# 10. 기존 Breathing과의 관계

기존 breathing은 유지한다.

역할은 권장은:

```text
1. blink
2. turn / shell / parallax
3. tilt
4. global breathing field
5. local chest soft morph
```

즉:

```text
breathing = ribcage / whole upper torso motion
chest soft = local cloth volume response
```

로 역할을 분리한다.

기존 `CHEST_WIDEN`은 Phase 1 구현 후:

- 유지
- 감소
- local morph로 대체

세 경우를 A/B한다.

장기적으로 기존 global widening을 약하게 줄이고 local morph가 대부분을 담당하는 편이 자연스러울 가능성이 크다.

---

# 11. Phase 2 — Soft Physics

Phase 1이 성공하면 secondary motion을 추가한다.

별도 physics 라이브러리는 필요 없다.

좌/우 zone 각각에 1D spring state만 있으면 충분하다.

```text
position
velocity
```

업데이트:

```text
accel = stiffness * (target - position) - damping * velocity
velocity += accel * dt
position += velocity * dt
```

타겟은:

```text
breath morph
+ 약한 body acceleration
+ 약한 turn response
```

를 합친 값.

---

## 11.1 권장 톤

- 숨 들어올 때 약간 늦게 따라옴
- 숨 내쉴 때 약하게 복귀
- head/body turn 방향 전환 시 1~2 frame 정도 아주 살짝 lag

금지:

- 독립적인 장식감 흔들림
- 큰 bounce
- collar/shoulder displacement

---

# 12. Turn Coupling

portrait의 yaw는 실제 3D 회전이 아니므로 coupling을 매우 약게 유지한다.

예:

```text
left_gain  = 1 - turnX * asymmetry
right_gain = 1 + turnX * asymmetry
```

또는 near/far side에 5~10% 수준의 차이만 준다.

목적은 "회전 시 좌우가 완전 동일하게 변형되어 평면 스티커처럼 보이는 것"을 줄이는 것이다.

Phase 1에는 넣지 않아도 된다.

---

# 13. Manifest 이슈

기존 `motion` 안에 넣는 것을 권장한다.

```json
{
  "motion": {
    "breathing": {
      "period_s": 4.0,
      "amplitude_px": 3.0
    },
    "upper_torso_soft_morph": {
      "enabled": true,
      "mode": "two_lobe",
      "strength": 1.0,
      "left": {
        "center": [0.39, 0.36],
        "radius": [0.24, 0.20]
      },
      "right": {
        "center": [0.61, 0.36],
        "radius": [0.24, 0.20]
      },
      "center_lock": 0.10,
      "neckline_lock": 0.16,
      "horizontal_px": 2.0,
      "vertical_px": 0.6,
      "confidence": 0.82,
      "source": "topwear_geometry"
    }
  }
}
```

중심/반경은 가능하면 part-local normalized coordinate로 저장한다.

그렇게 해야:

- crop 위치가 달라도 재사용 가능
- 해상도 독립
- 전신 확장 용이

---

# 14. Compiler 구조

`rig.py`의 모든 계산을 다 맡기보다 별도 모듈을 권장한다.

예:

```text
portrait_autorig/
  soft_morph.py
```

주요 함수:

```python
def derive_upper_torso_soft_region(...):
    ...


def soft_morph_preflight(...):
    ...
```

`rig.py`는:

```text
anchors 생성
→ soft region derive
→ manifest에 spec 기록
```

까지만 담당한다.

실제 per-frame deformation은 preview/runtime에서 수행한다.

---

# 15. Preflight

모든 캐릭터에 soft morph를 억지 적용하면 안 된다.

상태 예:

```text
READY
DEGRADED
DISABLED
```

### READY

- topwear 충분한 alpha 면적
- neck/body anchor 존재
- chest region이 canvas 안에 안정적으로 들어감

### DEGRADED

- loose robe / coat처럼 chest local geometry가 애매함
- torso crop이 너무 짧음
- remainder 의존도가 큼

### DISABLED

- topwear 없음
- torso가 거의 보이지 않음
- region 추정 confidence 낮음

낮은 confidence에서는 **아무 변화도 하지 않는 것이 정답**이다.

---

# 16. Garment Profile 후보

장기적으로 garment 특성별 multiplier를 둘 수 있다.

```text
soft_knit     1.00
shirt         0.70
cardigan      0.65
coat          0.25
robe          0.20
armor         0.00
```

하지만 Phase 1에서는 이미지 기반 옷 분류를 새로 만들지 않는다.

대신:

```text
manifest override / mod config
```

로만 제공해도 충분하다.

---

# 17. 연령 / 캐릭터 안전 규칙

시스템 기본값은 **비성적인 upper-torso breathing/cloth deformation**이어야 한다.

특히 캐릭터가 미성년/10대 프로필로 지정된 경우:

```text
secondary bust emphasis = disabled
```

으로 두고,

- 일반적인 흉곽 호흡
- 옷의 미세한 천 움직임

수준만 허용하는 것을 권장한다.

즉 강한 soft/bounce profile은 adult-only opt-in 데이터로 분리한다.

---

# 18. Preview UI 이슈

개발용 preview에만 우선 추가한다.

```text
[ ] Chest Soft Morph
Strength        0.00 ──── 1.00
Horizontal      0 ──── 4 px
Vertical        0 ──── 2 px
[ ] Soft Physics
Spring          ...
Damping         ...
[ ] Show Region
```

`Show Region`은 ellipse / weight heatmap 또는 wire overlay로 표시하면 디버깅이 쉬워진다.

실제 게임 런타임에는 이 UI가 필요 없다.

---

# 19. Mesh 요구사항

현재 topwear mesh가 너무 거칠면 soft morph가 faceting될 수 있다.

따라서 soft morph가 활성화된 topwear는:

```text
fine mesh
```

로 취급한다.

기존 fine cell 정책을 그대로 재사용하거나,
soft morph 활성 part에만 더 작은 cell을 적용한다.

단 Phase 1에서 adaptive mesh까지 갈 필요는 없다.

---

# 20. 반드시 지켜야 할 불변식

## A. Rest fidelity

```text
soft morph = 0
→ 기존 rig rest와 pixel-equivalent
```

## B. Neckline continuity

최대 morph에서도 neck/collar contact에 crack이 없어야 한다.

## C. Center stability

shirt/button/cardigan center line이 좌우로 크게 벌면 실패.

## D. Outer silhouette stability

어깨 및 torso side가 불필요하게 늘어나지 않아야 한다.

## E. Composition

turn + tilt + blink + breathing + morph를 동시에 켜도 NaN/flip/self-intersection 수준의 mesh failure가 없어야 한다.

---

# 21. A002 기준 1차 실험

A002는 cardigan + white shirt라 첫 실험에 적합하다.

권장 순서:

```text
A002
1. 현재 breathing baseline 저장
2. soft region overlay 확인
3. horizontal 1px
4. horizontal 2px
5. horizontal 3px
6. vertical 0 / 0.5 / 1px 비교
7. global CHEST_WIDEN on/off 비교
8. turnX ±0.4 + breathing + soft morph
9. neckline / center line 확인
```

초기 목표는:

```text
"가슴이 흔들린다"
```

보다

```text
"옷이 호흡에 맞춰 부드럽게 살짝 움직인다"
```

가 되어야 한다.

그 이후에만 Phase 2 secondary motion으로 넘어간다.

---

# 22. Acceptance Criteria — Phase 1

다음이 모두 충족되면 Phase 1 PASS.

1. soft morph OFF에서 기존 rig와 동일한 rest image
2. A002에서 neckline crack 없음
3. cardigan center/button line이 안정적
4. shoulder silhouette 변화가 거의 없음
5. inhale 시 chest local width/volume 변화가 시각적으로 인지됨
6. 기존 global breathing보다 상체가 덜 "통짜로 팽창"되어 보임
7. turn + breathing 조합에서도 mesh seam 없음
8. 저 confidence 캐릭터에서 안전 disable 가능
9. manifest에 hardcoded character-specific coordinates 없음
10. tests / preview 모두 기존 rig regression 없음

---

# 23. 구현 순서 권장

```text
Step 0  PMA renderer fix / baseline lock
Step 1  soft_morph.py + region derivation
Step 2  manifest schema
Step 3  preview region overlay
Step 4  static slider morph
Step 5  breathing coupling
Step 6  A002 A/B
Step 7  regression tests
------------------------------
Step 8  Phase 1 LOCK
------------------------------
Step 9  spring/damping secondary motion
Step 10 turn asymmetry coupling
```

---

# 24. 지금 당장 하지 말 것

- 좌/우 독립 bounce를 먼저 구현하지 말 것
- 별도 "breast" semantic layer를 만들지 말 것
- topwear를 더 조각으로 강제 분할하지 말 것
- body/head depth를 바꾸지 말 것
- physics를 위해 외부 엔진을 추가하지 말 것
- Spine exporter까지 동시에 손대지 말 것

먼저 **하나의 topwear mesh 위에서 local two-lobe deformation이 자연스럽게 되는지** 확인한다.

---

# 25. 최종 방향

이 기능의 최종 구조는 다음처럼 보는 것이 좋다.

```text
Upper Torso Motion
├── rigid/body breathing
├── ribcage widening
├── local soft cloth morph
└── optional secondary spring
```

즉 "버스트 모핑"은 별도의 장르 기능이 아니라,

> **상체 soft-deformation 시스템의 한 결과**

로 만든다.

이렇게 해두면 portrait를 넘어 full-body에서도 그대로:

- 흉곽
- 복부
- 소매
- 치마/로브
- 머리카락 soft zone

같은 generalized soft-region system으로 발전시킬 수 있다.

---

## v0.1 결론

**가능하며, 현재 `portrait-autorig` 구조에서 잘 맞는다.**

이미 존재하는 grid mesh + per-vertex deformation + breathing field 위에
`topwear` 전용 local two-lobe weight field를 한 겹 추가하는 것이 가장 싼 구현이다.

첫 목표는 과장된 bounce가 아니라:

> **A002 cardigan이 숨을 쉴 때 국소적으로 약 1~3px 부드럽게 볼륨 변화하는 것**

으로 잡는다.

그게 성공한 다음에만 spring / damping / turn asymmetry를 붙인다.
