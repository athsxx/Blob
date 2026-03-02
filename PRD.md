# 📘 PRODUCT REQUIREMENTS DOCUMENT (PRD)

## Multi-Camera Laser-Based Manifold Connectivity Inspection System

---

## 1. Executive Summary

### 1.1 Objective

Design and implement a **deterministic, multi-camera vision system** to verify **internal connectivity of drilled channels** in a 6-face manifold using **laser pass-light inspection**.

The system must:

* Detect laser light emerging from predefined holes
* Validate internal connectivity paths against engineering specifications
* Provide **real-time PASS / FAIL decisions**
* Be configurable via **machine-readable JSON**, not code changes

---

## 2. Scope of Work (For Antigravity)

Antigravity is expected to:

1. Refactor existing single-face blob detection into a **multi-camera architecture**
2. Implement a **central logic engine** driven by JSON rules
3. Build a **robust runtime state model**
4. Deliver a **single-window operator dashboard**
5. Ensure **industrial reliability** on NVIDIA Jetson hardware

---

## 3. Hardware Environment

### 3.1 Cameras

* **Model:** Arducam OV9281
* **Specs**
  * Global shutter
  * 120 FPS
  * 1 MP
  * USB UVC compliant
* **Quantity:** 6 (one per manifold face)

### 3.2 Compute

* **Host:** NVIDIA Jetson (Orin / Xavier / Super class)
* **OS:** Ubuntu (JetPack compatible)
* **Constraints**
  * No Docker
  * No web frameworks unless explicitly approved
  * Python-based solution preferred

---

## 4. Manifold Model

* **Faces:** A, B, C, D, E, F
* Each face contains multiple drilled holes
* Holes connect internally across faces
* Engineering connectivity is fixed and known (provided separately)

---

## 5. System Architecture

### 5.1 High-Level Architecture

```
+--------------------------------------------------+
|                  Jetson Host                     |
|                                                  |
|  +-----------+  +-----------+  +-----------+    |
|  | CAM_A     |  | CAM_B     |  | CAM_C     |    |
|  +-----------+  +-----------+  +-----------+    |
|        \             |              /           |
|         \            |             /            |
|          +-----------+------------+             |
|                      |                          |
|         +-------------------------------+       |
|         |   Central Logic Engine        |       |
|         |  - Rule Evaluation            |       |
|         |  - State Aggregation          |       |
|         |  - Inspection Result          |       |
|         +-------------------------------+       |
|                      |                          |
|         +-------------------------------+       |
|         |   Operator Dashboard          |       |
|         +-------------------------------+       |
+--------------------------------------------------+
```

---

## 6. Software Design Principles

1. **Single Detection Engine**
   * No face-specific code
   * Behavior driven entirely by configuration
2. **JSON-Driven System**
   * Cameras, ROIs, rules, workflows all externalized
3. **Deterministic Logic**
   * No ML inference in decision making
4. **Process Isolation**
   * Each camera runs independently
5. **Explainable Output**
   * Clear reason for every FAIL

---

## 7. Configuration Files (Mandatory)

### 7.1 `cameras.json`

Defines physical cameras and face mapping.

```json
{
  "cameras": [
    {
      "camera_id": "CAM_A",
      "usb_index": 0,
      "face": "A",
      "resolution": [1280, 800],
      "fps": 120,
      "enabled": true
    }
  ]
}
```

---

### 7.2 `rois.json`

Maps physical holes to pixel coordinates.

```json
{
  "rois": [
    {
      "roi_id": "A_A1",
      "camera_id": "CAM_A",
      "face": "A",
      "hole_id": "A1",
      "shape": "circle",
      "cx": 642,
      "cy": 381,
      "radius": 18
    }
  ]
}
```

---

### 7.3 `connectivity_rules.json` (Core Logic)

Defines expected internal connectivity.

```json
{
  "rules": [
    {
      "rule_id": "FACE_A_A1",
      "input": {
        "face": "A",
        "hole_id": "A1"
      },
      "expected_outputs": [
        { "face": "F", "hole_id": "A2", "mandatory": true },
        { "face": "D", "hole_id": "A25", "mandatory": true }
      ],
      "logic": "AND",
      "timing": {
        "max_delay_ms": 200,
        "min_stable_frames": 3
      }
    }
  ]
}
```

---

### 7.4 `inspection_sequences.json`

Defines operator inspection order.

```json
{
  "inspection_sequences": [
    {
      "sequence_id": "FACE_A",
      "steps": [
        {
          "step_id": 1,
          "input_hole": { "face": "A", "hole_id": "A1" },
          "rule_id": "FACE_A_A1"
        }
      ]
    }
  ]
}
```

---

## 8. Camera Process Requirements

Each camera process must:

* Load ROI config
* Filter ROIs by `camera_id`
* Perform laser/blob detection per ROI
* Output detection results via IPC

### Output Contract

```json
{
  "camera_id": "CAM_B",
  "timestamp": 1712345678,
  "detections": [
    {
      "roi_id": "B_B16",
      "laser": true,
      "confidence": 0.94
    }
  ]
}
```

---

## 9. Central Logic Engine

### Responsibilities

* Maintain global ROI state
* Apply temporal stability logic
* Evaluate active connectivity rules
* Emit PASS / FAIL with reason

### Global State Model

```python
global_roi_state = {
  "A_A1": false,
  "B_B16": true
}
```

---

## 10. Timing & Stability Requirements

* Laser must be detected for **N consecutive frames**
* Output must occur within **max_delay_ms**
* Flickering or transient detections must be ignored

---

## 11. Operator Dashboard Requirements

* Single unified window
* Live feed from all cameras
* ROI overlays
* Color coding:
  * Green → detected
  * Red → missing expected output
* Textual PASS / FAIL summary
* Display missing hole IDs on FAIL

---

## 12. Output & Logging

### Inspection Result Schema

```json
{
  "inspection_id": "2024-09-21-001",
  "input_hole": "A_A1",
  "result": "FAIL",
  "missing_outputs": ["D_A25"],
  "timestamp": 1712345699
}
```

### Logging

* CSV + JSON logs
* One record per inspection
* Camera health included

---

## 13. Error Handling & Reliability

| Failure           | Expected Behavior             |
| ----------------- | ----------------------------- |
| Camera disconnect | Auto-recover without crashing |
| Missing laser     | Explicit FAIL                 |
| Partial detection | FAIL with reason              |
| Unknown state     | FAIL safe                     |

---

## 14. Non-Functional Requirements

| Category        | Requirement          |
| --------------- | -------------------- |
| Latency         | <30 ms per frame     |
| Uptime          | 24×7 capable         |
| Maintainability | Config-only changes  |
| Scalability     | Up to 6 cameras      |
| Portability     | Jetson compatible    |
| Explainability  | Rule-based decisions |

---

## 15. Deliverables Expected from Antigravity

1. Modular Python codebase
2. Fully documented JSON schemas
3. Logic engine implementation
4. Operator dashboard
5. Deployment instructions for Jetson
6. Test cases & validation report

---

## 16. Explicit Non-Goals

* No deep learning
* No cloud dependency
* No automatic hole discovery
* No dynamic rule inference

---

## 17. Success Criteria

The system is successful if:

* Any missing internal connection is detected
* Every FAIL has a clear explanation
* New manifold variants require **only JSON changes**
* Operators can use the system with minimal training

---

## 18. Final Note

This system is designed to be:

* **Deterministic**
* **Auditable**
* **Manufacturing-grade**
* **Future-extensible**
