# PORTRAIT AUTORIG — PARAMETER EXPRESSION DESIGN v0.1

> Status: **DESIGN / IMPLEMENTATION DIRECTIVE**
>
> Scope: layer-free facial expressions, `ParamMouthForm`, ExpressionPreset v2 semantics
>
> Repository: `prentice7725/portrait-autorig`
>
> Date: 2026-09-15

---

## 0. Decision

Portrait AutoRig의 표정 시스템을 다음 원칙으로 확장한다.

> **Expression = parameter pose + optional variant swap**

표정마다 새 그림 레이어를 요구하지 않는다.

기본 표정은 기존 파츠와 메쉬를 변형해서 만든다.
원본에 존재하지 않는 픽셀이 필요한 경우에만 Variant / donor art를 사용한다.

첫 구현 대상은 다음이다.

```text
ParamMouthOpenY -> jaw_open       # existing
ParamMouthForm  -> mouth_form     # new
```

`ParamMouthForm`의 의미는 다음처럼 고정한다.

```text
-1.0           0.0           +1.0
Frown        Neutral         Smile
```

---

## 1. Current State

현재 Rig Manifest v0.2 parameter registry에는 이미 다음이 존재한다.

```text
ParamMouthOpenY  0..1
ParamMouthForm  -1..1
```

하지만 현재 실제 deformation path는 `ParamMouthOpenY -> jaw_open`까지만 구현되어 있다.

`ParamMouthForm`은 registry/UI에 존재하지만 이를 소비하는 deformer가 없다.

또한 현재 ExpressionPreset은 Composer VariantSet 선택 묶음으로 컴파일된다.

즉 현재 의미는 사실상 다음이다.

```text
ExpressionPreset = Variant selections
```

이를 다음으로 확장한다.

```text
ExpressionPreset
  = Parameter pose
  + optional Variant selections
```

---

## 2. Why Layer-Free Expressions

Smile, Frown, Smirk처럼 기존 선을 움직이는 표정은 새 그림이 필요하지 않다.

새 expression layer를 계속 추가하면 다음 문제가 생긴다.

- actor마다 expression layer 수가 증가
- Composer variant graph 복잡도 증가
- donor generation 비용 증가
- identity drift 검증 대상 증가
- full-body 확장 시 expression asset 폭증
- Runtime sprite swap 의존 증가

반대로 parameter expression은 같은 원화를 유지하면서 값만 움직인다.

```text
Neutral art
   ↓
mesh / corrective field
   ↓
Smile / Frown / Smirk
```

따라서 기본 표정은 rig에서 만들고, 그림 교체는 예외로 둔다.

---

## 3. What Can Be Parameter-Driven

### Layer-free 권장

- subtle Smile
- Frown
- Smirk
- asymmetric mouth corner
- mild annoyance
- subtle sadness
- brow raise / brow lower (future)
- eye-smile / squint (future, drawing-dependent)

### Variant / donor art 권장

- teeth-visible smile
- large open laugh
- tongue / teeth / inner-mouth drawing
- strongly stylized mouth shapes
- source art에 존재하지 않는 closed-eye drawing
- source art에 없는 symbol/comic expression

판단 규칙은 단순하다.

> **기존 픽셀의 위치/형태 변화로 표현할 수 있으면 parameter. 새 픽셀이 필요하면 variant.**

---

## 4. New Deformer: `mouth_form`

새 deformer kind를 추가한다.

```text
DEFORMER_MOUTH_FORM = "mouth_form"
```

manifest example:

```json
{
  "id": "mouth_form",
  "kind": "mouth_form",
  "parameters": ["ParamMouthForm"],
  "targets": {
    "tags": ["mouth", "face"]
  },
  "config": {
    "version": 1
  },
  "phase": "corrective"
}
```

`mouth_form`은 새 sprite를 생성하지 않는다.

기존 `mouth` mesh와 필요 시 `face` mesh에 corrective displacement를 준다.

---

## 5. Mouth Form Geometry

### 5.1 Semantic control points

최소 의미점:

```text
 cheek L                 cheek R
    o                        o

       o ------ o ------ o
     corner    center    corner
       L                   R
```

필수 anchor:

- left mouth corner
- mouth center
- right mouth corner

선택 anchor:

- left cheek influence center
- right cheek influence center

AutoRig는 기존 mouth alpha/bounding box와 face geometry에서 초기값을 유도한다.

### 5.2 Smile (`ParamMouthForm > 0`)

기본 동작:

```text
left corner   -> left + up
right corner  -> right + up
center        -> almost fixed
near-mouth face -> weak upward/outward falloff
```

목표는 입 전체를 통째로 위로 옮기는 것이 아니다.

입 중앙은 최대한 유지하고 양쪽 끝의 곡률을 만든다.

### 5.3 Frown (`ParamMouthForm < 0`)

기본 동작:

```text
left corner   -> inward + down
right corner  -> inward + down
center        -> slight down or fixed
near-mouth face -> weak downward falloff
```

Smile의 단순 역변환으로만 만들지 않는다.

Smile/Frown은 같은 axis를 공유하되 endpoint keyform은 독립 설정 가능해야 한다.

---

## 6. Mouth Part + Face Corrective

mouth sprite만 휘면 얼굴 위에 붙인 스티커처럼 보일 수 있다.

따라서 deformation은 두 층으로 나눈다.

```text
ParamMouthForm
    ├─ mouth mesh deformation      # strong
    └─ face corrective field       # subtle
```

face corrective는 입 주변에 국한한다.

권장 영향:

```text
mouth corner : 1.0
near cheek   : 0.15 ~ 0.30
far cheek    : 0
jaw/chin     : near 0 for closed-mouth smile
```

정확한 수치는 character geometry 기반으로 정규화하고 heuristic registry에서 튜닝한다.

---

## 7. Interaction with `jaw_open`

`ParamMouthForm`과 `ParamMouthOpenY`는 독립 축이다.

```text
ParamMouthForm  = shape/emotion
ParamMouthOpenY = opening amount
```

예:

```text
Smile + closed mouth
MouthForm = +0.75
MouthOpen = 0.00

Smile + talking
MouthForm = +0.55
MouthOpen = 0.0..1.0
```

두 deformer는 corrective phase에서 deterministic order를 가져야 한다.

v0.1 권장:

```text
mouth_form
   ↓
jaw_open
```

즉 먼저 입의 감정 곡률을 만든 뒤 jaw/open displacement를 적용한다.

다만 실제 runtime implementation은 phase 내부의 explicit order를 contract로 기록해야 한다.

---

## 8. ExpressionPreset v2

현재 variant-only preset을 하위 호환으로 유지하면서 parameter map을 허용한다.

### Parameter-only Smile

```json
{
  "smile": {
    "parameters": {
      "ParamMouthForm": 0.72
    }
  }
}
```

### Parameter-only Happy

```json
{
  "happy": {
    "parameters": {
      "ParamMouthForm": 0.78,
      "ParamEyeLOpen": 0.90,
      "ParamEyeROpen": 0.90
    }
  }
}
```

### Hybrid expression

```json
{
  "big_smile": {
    "variants": {
      "mouth": "mouth_teeth_smile"
    },
    "parameters": {
      "ParamMouthForm": 0.25
    }
  }
}
```

### Backward compatibility

기존 preset:

```json
{
  "blink_special": {
    "variants": {
      "eyes": "eyes_closed"
    }
  }
}
```

은 그대로 유효하다.

Validation rule:

```text
ExpressionPreset must contain at least one of:
- parameters
- variants
```

둘 다 존재해도 된다.

---

## 9. Expression Lifecycle

Rig Controller는 expression을 preset id가 아니라 resolved pose로 적용한다.

```text
setExpression("smile")
   ↓
resolve preset
   ├ parameter targets
   └ variant selections
   ↓
apply
```

release:

```text
releaseExpression()
   ↓
restore expression-owned parameters
   ↓
restore variant defaults
```

중요:

Expression release가 manual slider 값을 지워서는 안 된다.

기존 parameter arbitration에 expression source를 추가한다.

권장 priority:

```text
EDIT
 > MANUAL
 > HOST / SCRIPTED
 > EXPRESSION
 > CURSOR
 > AUTO_IDLE
```

단, 게임 host가 expression 자체를 scripted control로 사용하는 경우 controller API에서 source를 지정할 수 있다.

---

## 10. Rig Studio UX

Preview의 Expression section은 parameter-only preset도 표시해야 한다.

```text
Expressions
[Neutral] [Smile] [Frown] [Smirk] [Big Smile]
```

사용자는 내부적으로 이것이 parameter인지 variant인지 알 필요가 없다.

Edit > Face > Mouth에는 다음을 추가한다.

```text
Mouth Form

Frown    --------o--------    Smile
           0.00

[Edit -1 Keyform]
[Edit +1 Keyform]
[Reset to Auto]
```

장기적으로 Rig Studio에서 mouth corner/keyform을 직접 수정할 수 있다.

---

## 11. Generated / Authoring Ownership

AutoRig는 초기 mouth form field/keyforms를 생성한다.

```text
generated/
  mouth_form
```

사람 보정은 `authoring/`에 저장한다.

예:

```json
{
  "deformers": {
    "mouth_form": {
      "keyform_overrides": {
        "-1": {},
        "+1": {}
      }
    }
  }
}
```

정확한 persistence shape는 기존 Rig Project override convention을 따른다.

Composer는 최종 mouth mesh/keyform을 소유하지 않는다.

---

## 12. Composer Boundary

Composer가 계속 소유하는 것:

- mouth semantic layer
- optional mouth variants
- expression state graph when explicit art variants exist
- optional qualitative hints

Rig Studio / AutoRig가 소유하는 것:

- mouth mesh
- mouth_form deformer
- mouth_form keyforms
- face corrective field
- parameter range
- rig-side expression parameter pose

즉 Composer에 Smile용 새 레이어를 요구하지 않는다.

---

## 13. Full-body Compatibility

이 설계는 Portrait 전용 예외가 아니다.

장기적으로 동일한 Expression/Parameter pose 시스템을 full-body pose에도 확장할 수 있다.

```text
Expression / Pose Preset
  ├ facial parameters
  ├ body parameters
  └ optional visual variants
```

따라서 현재 variant-only expression 모델보다 전신 확장에 유리하다.

---

## 14. Implementation Slices

### R6-A — Mouth Form Runtime

- `DEFORMER_MOUTH_FORM` 추가
- `ParamMouthForm`을 deformer에 연결
- mouth mesh displacement 구현
- face corrective field 구현
- deterministic corrective ordering

Acceptance:

- Neutral exact rest
- +1 Smile readable
- -1 Frown readable
- no new layer required
- no mouth/face seam separation

### R6-B — Parameter Expression Presets

- `ExpressionPreset.parameters` schema 추가
- variants optional화
- parameters-only preset 허용
- hybrid preset 허용
- controller catalog 수정

Acceptance:

- `{parameters:{ParamMouthForm:0.7}}` preset loads
- old variants-only preset remains valid
- hybrid applies atomically

### R6-C — Expression Ownership / Release

- expression parameter source 추가
- release restores previous owner/value correctly
- manual slider priority 보장

### R6-D — Rig Studio Mouth Authoring

- Mouth semantic inspector
- ParamMouthForm slider
- -1/+1 keyform preview
- author override save/reset

### R6-E — QA

QA presets:

```text
Smile +1
Smile +0.5
Neutral
Frown -0.5
Frown -1
Smile + MouthOpen
Frown + MouthOpen
```

검사:

- triangle inversion
- lip stretching
- face seam
- texture over-stretch
- mouth-open composition

---

## 15. Tests

필수 automated tests:

1. `ParamMouthForm=0` gives exact rest geometry.
2. `ParamMouthForm` clamps to `[-1,1]`.
3. left/right corner displacement is symmetric for symmetric source geometry.
4. Smile corners move upward relative to neutral.
5. Frown corners move downward relative to neutral.
6. face corrective goes to zero outside influence region.
7. `MouthForm + MouthOpen` is deterministic regardless of frame history.
8. parameter-only ExpressionPreset validates.
9. variants-only legacy ExpressionPreset validates.
10. hybrid ExpressionPreset applies both parameter and variant state.
11. release restores neutral expression without overwriting manual claims.
12. expression preset requires `parameters` or `variants`.

Visual fixture tests should include at least:

- thin-line closed mouth
- thicker anime mouth
- asymmetric mouth drawing
- small mouth
- wide mouth

---

## 16. Non-goals

R6에서는 다음을 하지 않는다.

- teeth synthesis
- tongue synthesis
- AI-generated smile art
- phoneme/viseme authoring system
- full facial FACS system
- automatic emotion inference
- timeline animation editor

---

## 17. Implementation Lock

다음을 잠근다.

1. Smile/Frown/Smirk의 기본 경로는 새 레이어가 아니라 `ParamMouthForm`이다.
2. `ParamMouthForm`은 기존 mouth mesh + subtle face corrective를 구동한다.
3. `ParamMouthOpenY`와 `ParamMouthForm`은 독립 축이다.
4. ExpressionPreset은 parameter pose를 지원하도록 확장한다.
5. Variant swap은 optional이다.
6. 새 픽셀이 필요한 표정에만 donor/variant art를 사용한다.
7. Composer는 mouth rig keyform을 소유하지 않는다.
8. AutoRig가 generated base를 만들고 Rig Studio가 override를 소유한다.
9. 기존 variants-only preset은 깨지지 않는다.
10. 이 구조를 향후 eyebrow/eye-smile/full-body parameter pose의 기반으로 사용한다.

---

## 18. Recommended Next Slice

다음 구현 작업은:

> **R6-A — `ParamMouthForm -> mouth_form` corrective deformer**

이다.

이 slice에서는 ExpressionPreset schema를 아직 바꾸지 않아도 된다.

먼저 QA slider로 `ParamMouthForm`을 직접 움직여 geometry quality를 검증한다.

Smile/Frown deformation이 시각적으로 통과한 뒤 R6-B에서 parameter-only ExpressionPreset을 연결한다.

이 순서가 가장 안전하다.
